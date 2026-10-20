package xiaozhi.modules.officialtts.engine;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Base64;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

import xiaozhi.modules.officialtts.entity.OfficialTtsAssetEntity;
import xiaozhi.modules.officialtts.entity.OfficialTtsJobEntity;
import xiaozhi.modules.officialtts.entity.OfficialTtsLedgerEntity;
import xiaozhi.modules.officialtts.entity.OfficialTtsVoiceEntity;

/**
 * Executes clone/design/job against the gateway and persists results.
 * Does not write a second one-api debit; quota comes from the gateway ledger.
 */
public class OfficialTtsEngine {
    public final OfficialTtsGatewayClient gateway;
    public final OfficialTtsPriceGate prices;
    public final Store store;
    public final Path root;
    public final String mediaSecret;

    /** 复刻音色补预览时使用的默认试听文案（与前端设计页默认值一致）。 */
    private static final String DEFAULT_PREVIEW_TEXT = "欢迎使用文本朗读，这是一段设计的音色。";
    /** 无任务号/账单号的提交期中断，超过该时长即判定为失败。 */
    private static final long STALE_SUBMIT_MILLIS = 10 * 60 * 1000L;
    /** 同一音色补预览的最小重试间隔，避免列表刷新时反复合成计费。 */
    private static final long PREVIEW_RETRY_MILLIS = 60 * 1000L;
    /**
     * voiceId -> 上次尝试补预览的时间戳。
     * 必须 static：engine() 每次请求都会 new 一个新实例，实例级 map 起不到限流作用，
     * 会让「补预览失败」在每次列表刷新时反复重试并重复计费。
     */
    private static final ConcurrentHashMap<Long, Long> previewAttemptAt = new ConcurrentHashMap<>();
    public final String mediaPublicBase;

    public OfficialTtsEngine(OfficialTtsGatewayClient gateway, OfficialTtsPriceGate prices, Store store,
            Path root, String mediaSecret, String mediaPublicBase) {
        this.gateway = gateway;
        this.prices = prices;
        this.store = store;
        this.root = root;
        this.mediaSecret = mediaSecret;
        this.mediaPublicBase = mediaPublicBase.replaceAll("/+$", "");
        if (this.mediaSecret == null || this.mediaSecret.isBlank()) {
            throw new IllegalStateException("media_secret_required");
        }
    }

    /**
     * 提交复刻/设计。任何提交期异常都要把任务收敛为失败，
     * 否则会留下永远「处理中」的僵尸记录（前端会一直显示生成中）。
     */
    public OfficialTtsVoiceEntity createVoice(long userId, String token, String idem, Map<String, Object> body,
            byte[] audio) {
        try {
            return createVoiceInternal(userId, token, idem, body, audio);
        } catch (RuntimeException e) {
            markVoiceSubmitAborted(userId, idem, e);
            throw e;
        }
    }

    private void markVoiceSubmitAborted(long userId, String idem, RuntimeException e) {
        if (idem == null || idem.isBlank()) {
            return;
        }
        try {
            OfficialTtsVoiceEntity row = store.findVoiceByIdem(userId, idem);
            if (row == null) {
                return;
            }
            // 已由上游定论或已冻结配额的不在此覆盖，避免掩盖真实对账状态
            if (!"processing".equals(row.getStatus()) || row.getBillId() != null) {
                return;
            }
            row.setStatus("failed");
            row.setErrorMsg(friendlySubmitError(e));
            row.setUpdatedAt(new Date());
            store.saveVoice(row);
        } catch (RuntimeException ignored) {
            // 收敛失败不应掩盖原始异常
        }
    }

    private static String friendlySubmitError(RuntimeException e) {
        String msg = e.getMessage() == null ? "" : e.getMessage();
        if (msg.contains("audio_url_not_allowed")) {
            return "复刻音频地址未被网关允许，请核对 official.tts.media.base 与网关 BAILIAN_MEDIA_HOSTS 是否一致";
        }
        if (msg.contains("media_secret_required")) {
            return "缺少媒体签名密钥（official.tts.media.secret）";
        }
        if (msg.startsWith("gateway_unreachable")) {
            return "网关不可达，请稍后重试（" + msg + "）";
        }
        if (msg.startsWith("gateway_http_")) {
            return "上游拒绝了本次提交（" + msg + "）";
        }
        return msg.isBlank() ? "submit_aborted" : msg;
    }

    private OfficialTtsVoiceEntity createVoiceInternal(long userId, String token, String idem,
            Map<String, Object> body, byte[] audio) {
        if (token == null || token.isBlank()) {
            throw new IllegalStateException("customer_token_required");
        }
        if (idem == null || idem.isBlank()) {
            throw new IllegalArgumentException("idempotency_key_required");
        }
        String kind = String.valueOf(body.getOrDefault("kind", "clone"));
        if ("import".equals(kind)) {
            throw new IllegalArgumentException("import_not_supported");
        }
        String canonical = canonical(kind, body);
        String hash = OfficialTtsVoiceAcl.payloadHash(canonical);
        OfficialTtsVoiceEntity existing = store.findVoiceByIdem(userId, idem);
        if (existing != null) {
            if (!hash.equals(phash(existing))) {
                throw new IllegalArgumentException("idempotency_payload_conflict");
            }
            return refreshVoice(userId, token, existing);
        }
        String op = switch (kind) {
            case "design" -> "design";
            default -> "clone";
        };
        OfficialTtsPriceGate.Frozen frozen = prices.require(op, OfficialTtsPriceGate.MODEL, OfficialTtsPriceGate.REGION, "count");
        OfficialTtsVoiceEntity row = new OfficialTtsVoiceEntity();
        row.setUserId(userId);
        row.setKind(kind);
        row.setName(String.valueOf(body.getOrDefault("name", "我的音色")));
        row.setTargetModel(OfficialTtsPriceGate.MODEL);
        row.setChannel("bailian");
        row.setRegion(OfficialTtsPriceGate.REGION);
        row.setStatus("processing");
        row.setIdempotencyKey(idem);
        row.setLanguageHints(hintsWithHash(body, hash));
        row.setCreatedAt(new Date());
        row.setUpdatedAt(new Date());
        store.saveVoice(row);
        Map<String, Object> gwBody = new HashMap<>();
        gwBody.put("model", OfficialTtsPriceGate.MODEL);
        gwBody.put("region", OfficialTtsPriceGate.REGION);
        gwBody.put("prefix", voicePrefix(userId));
        if ("clone".equals(kind)) {
            if (audio == null || audio.length == 0) {
                throw new IllegalArgumentException("clone_audio_required");
            }
            OfficialTtsAudioInspector.Result wav = OfficialTtsAudioInspector.inspectWav(audio);
            OfficialTtsAssetEntity asset = new OfficialTtsAssetEntity();
            asset.setUserId(userId);
            asset.setPurpose("clone_source");
            try {
                Files.createDirectories(root);
                Path dest = root.resolve(userId + "-" + UUID.randomUUID() + ".wav");
                Files.write(dest, audio);
                asset.setStoragePath(dest.toString());
            } catch (Exception e) {
                throw new IllegalStateException("asset_store_failed", e);
            }
            asset.setMimeType(wav.mime);
            asset.setDurationMs(wav.durationMs);
            asset.setExpireAt(Date.from(Instant.now().plusSeconds(86400)));
            store.saveAsset(asset);
            if (mediaSecret == null || mediaSecret.isBlank()) {
                throw new IllegalStateException("media_secret_required");
            }
            String tok = OfficialTtsMediaToken.issue(mediaSecret, userId, asset.getId(), Instant.now().plusSeconds(3600));
            gwBody.put("audio_url", mediaPublicBase + "/official-tts/internal/media/" + tok);
            gwBody.put("audio_sha256", sha256Hex(audio));
            gwBody.put("language_hints", List.of("zh"));
            Map<String, Object> resp = gateway.cloneVoice(token, idem, gwBody);
            long frozenQuota = applyGatewayVoice(row, resp, frozen);
            store.saveVoice(row);
            if ("failed".equals(row.getStatus())) {
                throw new IllegalStateException(firstNonBlank(row.getErrorMsg(), "upstream_failed"));
            }
            if (frozenQuota > 0) {
                writeLedger(userId, null, "reserve", row.getBillId(), frozenQuota);
            }
        } else if ("design".equals(kind)) {
            String prompt = String.valueOf(body.getOrDefault("prompt", "")).trim();
            if (prompt.isEmpty()) {
                prompt = String.valueOf(body.getOrDefault("voicePrompt", body.getOrDefault("voice_prompt", ""))).trim();
            }
            String preview = String.valueOf(body.getOrDefault("previewText", body.getOrDefault("preview_text", ""))).trim();
            if (prompt.isEmpty() || preview.isEmpty()) {
                throw new IllegalArgumentException("design_prompt_and_preview_required");
            }
            if (preview.codePointCount(0, preview.length()) < 15) {
                throw new IllegalArgumentException("preview_text_min_15_chars");
            }
            if ("设计音色".equals(row.getName()) || row.getName() == null || row.getName().isBlank()) {
                String shortName = prompt.length() > 24 ? prompt.substring(0, 24) + "…" : prompt;
                row.setName(shortName);
            }
            gwBody.put("prompt", prompt);
            gwBody.put("preview_text", preview);
            Map<String, Object> resp = gateway.designVoice(token, idem, gwBody);
            long frozenQuota = applyGatewayVoice(row, resp, frozen);
            store.saveVoice(row);
            persistDesignPreview(row, resp);
            store.saveVoice(row);
            if ("failed".equals(row.getStatus())) {
                throw new IllegalStateException(firstNonBlank(row.getErrorMsg(), "upstream_failed"));
            }
            if (frozenQuota > 0) {
                writeLedger(userId, null, "reserve", row.getBillId(), frozenQuota);
            }
        } else {
            throw new IllegalArgumentException("unknown_kind:" + kind);
        }
        store.saveVoice(row);
        return refreshVoice(userId, token, row);
    }

    public OfficialTtsVoiceEntity refreshVoice(long userId, String token, OfficialTtsVoiceEntity row) {
        if (row == null || !Objects.equals(userId, row.getUserId())) {
            throw new IllegalArgumentException("voice_not_found");
        }
        boolean pending = "processing".equals(row.getStatus()) || "uncertain".equals(row.getStatus());
        String task = null;
        if (row.getErrorMsg() != null && row.getErrorMsg().startsWith("task:")) {
            task = row.getErrorMsg().substring(5);
        }
        if (pending && task != null && token != null) {
            try {
                Map<String, Object> resp = gateway.voiceTask(token, task);
                String status = str(resp.get("status"));
                if ("available".equals(status)) {
                    row.setStatus("available");
                    row.setUpstreamVoiceId(str(resp.get("voice_id")));
                    if (row.getErrorMsg() != null && row.getErrorMsg().startsWith("task:")) {
                        // keep task id for audit; status drives UI
                    }
                } else if ("failed".equals(status)) {
                    row.setStatus("failed");
                } else if ("uncertain".equals(status)) {
                    row.setStatus("uncertain");
                } else if ("processing".equals(status)) {
                    row.setStatus("processing");
                }
                if (resp.get("voice_id") != null) {
                    row.setUpstreamVoiceId(str(resp.get("voice_id")));
                }
                row.setUpdatedAt(new Date());
                store.saveVoice(row);
            } catch (RuntimeException ignored) {
                // keep prior status; next poll retries
            }
        }
        // 兜底：没有任务号也没有账单号，且长时间未推进的任务不可能再有结果（提交期中断），
        // 收敛为失败，避免前端永久显示「生成中」。
        if (pending && task == null && row.getBillId() == null && row.getCreatedAt() != null
                && System.currentTimeMillis() - row.getCreatedAt().getTime() > STALE_SUBMIT_MILLIS) {
            row.setStatus("failed");
            row.setErrorMsg("submit_aborted_no_bill");
            row.setUpdatedAt(new Date());
            store.saveVoice(row);
        }
        if ("available".equals(row.getStatus())) {
            ensureVoicePreview(userId, token, row);
        }
        return row;
    }

    /**
     * 为已就绪的音色补齐试听音频（best-effort，失败不影响音色本身可用）。
     * 复刻音色上游只回传音色 ID，不会像设计音色那样附带预览音频，故此处按需补一次。
     */
    public boolean ensureVoicePreview(long userId, String token, OfficialTtsVoiceEntity row) {
        return ensureVoicePreview(userId, token, row, false);
    }

    /**
     * @param userInitiated 用户主动点击试听时为 true：忽略冷却期，务必真正尝试一次，
     *                      否则自动补预览刚失败过时，用户的点击会被静默吞掉。
     */
    public boolean ensureVoicePreview(long userId, String token, OfficialTtsVoiceEntity row, boolean userInitiated) {
        if (row == null || row.getId() == null || token == null || token.isBlank()) {
            return false;
        }
        if (hasVoicePreview(row)) {
            return true;
        }
        if (!"available".equals(row.getStatus())
                || row.getUpstreamVoiceId() == null || row.getUpstreamVoiceId().isBlank()) {
            return false;
        }
        long now = System.currentTimeMillis();
        if (!userInitiated) {
            Long last = previewAttemptAt.get(row.getId());
            if (last != null && now - last < PREVIEW_RETRY_MILLIS) {
                return false;
            }
        }
        previewAttemptAt.put(row.getId(), now);
        try {
            prices.require("preview", OfficialTtsPriceGate.MODEL, OfficialTtsPriceGate.REGION, "weighted_character");
            Map<String, Object> gwBody = new HashMap<>();
            gwBody.put("model", OfficialTtsPriceGate.MODEL);
            gwBody.put("voice", row.getUpstreamVoiceId());
            gwBody.put("text", DEFAULT_PREVIEW_TEXT);
            gwBody.put("format", "wav");
            gwBody.put("sample_rate", 16000);
            gwBody.put("operation", "preview");
            Map<String, Object> resp = gateway.synthesize(token, "voice-preview-" + row.getId(), gwBody);
            Object audio = resp.get("audio");
            if (audio == null) {
                return false;
            }
            String b64 = String.valueOf(audio).trim();
            if (b64.isEmpty() || "null".equals(b64)) {
                return false;
            }
            byte[] bytes = OfficialTtsAudioInspector.normalizeWav(Base64.getDecoder().decode(b64));
            Files.createDirectories(root);
            Path dest = root.resolve("voice-preview-" + row.getId() + ".wav");
            Files.write(dest, bytes);
            row.setPreviewUrl(dest.toString());
            row.setUpdatedAt(new Date());
            store.saveVoice(row);
            OfficialTtsAssetEntity asset = new OfficialTtsAssetEntity();
            asset.setUserId(row.getUserId());
            asset.setVoiceId(row.getId());
            asset.setPurpose("voice_preview");
            asset.setStoragePath(dest.toString());
            asset.setMimeType("audio/wav");
            asset.setExpireAt(Date.from(Instant.now().plusSeconds(86400L * 30)));
            asset.setCreatedAt(new Date());
            store.saveAsset(asset);
            return true;
        } catch (RuntimeException | java.io.IOException e) {
            // 不能静默吞掉：用户点击试听失败时要能在日志里定位原因（价格未配/网关不可达等）
            System.err.println("[official-tts] ensureVoicePreview failed voiceId=" + row.getId()
                    + " userId=" + userId + " : " + e.getMessage());
            return false;
        }
    }

    public byte[] downloadVoicePreview(long userId, OfficialTtsVoiceEntity row) {
        if (row == null || !Objects.equals(userId, row.getUserId())) {
            throw new IllegalArgumentException("voice_not_found");
        }
        String path = row.getPreviewUrl();
        if (path == null || path.isBlank() || !(path.endsWith(".wav") || path.endsWith(".mp3"))) {
            throw new IllegalArgumentException("preview_unavailable");
        }
        try {
            return Files.readAllBytes(Path.of(path));
        } catch (Exception e) {
            throw new IllegalStateException("preview_read_failed", e);
        }
    }

    public boolean hasVoicePreview(OfficialTtsVoiceEntity row) {
        if (row == null || row.getPreviewUrl() == null) {
            return false;
        }
        String path = row.getPreviewUrl();
        if (!(path.endsWith(".wav") || path.endsWith(".mp3"))) {
            return false;
        }
        try {
            return Files.isRegularFile(Path.of(path));
        } catch (Exception e) {
            return false;
        }
    }

    public void deleteVoice(long userId, String token, OfficialTtsVoiceEntity row, boolean bound) {
        if (bound) {
            throw new IllegalStateException("voice_in_use");
        }
        if (row.getUpstreamVoiceId() != null && !row.getUpstreamVoiceId().isBlank()) {
            try {
                Map<String, Object> resp = gateway.deleteVoice(token, row.getUpstreamVoiceId());
                if ("uncertain".equals(resp.get("status"))) {
                    row.setStatus("uncertain");
                    row.setErrorMsg("delete_uncertain");
                    row.setUpdatedAt(new Date());
                    store.saveVoice(row);
                    return;
                }
            } catch (IllegalStateException e) {
                String msg = e.getMessage() == null ? "" : e.getMessage();
                // Upstream already gone / id rejected: still remove local asset so UI can clean up.
                boolean gone = msg.contains("voice_not_found") || msg.contains("invalid_voice")
                        || msg.contains("gateway_http_404") || msg.contains("gateway_http_400");
                if (!gone) {
                    throw e;
                }
            }
        }
        row.setStatus("deleted");
        row.setUpdatedAt(new Date());
        store.saveVoice(row);
    }

    public OfficialTtsJobEntity createJob(long userId, String token, String idem, Map<String, Object> body,
            List<String> allowedVoices) {
        if (token == null || token.isBlank()) {
            throw new IllegalStateException("customer_token_required");
        }
        if (idem == null || idem.isBlank()) {
            throw new IllegalArgumentException("idempotency_key_required");
        }
        String jobType = String.valueOf(body.getOrDefault("jobType", "dubbing"));
        if ("preview".equals(jobType)) {
            // 预览（低成本试听）已下线：合成一律走真实合成并真实计费
            throw new IllegalArgumentException("preview_not_supported");
        }
        if (!"dubbing".equals(jobType)) {
            throw new IllegalArgumentException("unknown_job_type:" + jobType);
        }
        String voice = String.valueOf(body.getOrDefault("voice", "longanlingxi"));
        OfficialTtsVoiceAcl.require(voice, allowedVoices);
        String canonical = canonical(jobType, body);
        String hash = OfficialTtsVoiceAcl.payloadHash(canonical);
        OfficialTtsJobEntity existing = store.findJobByIdem(userId, idem);
        if (existing != null) {
            if (!hash.equals(phashJob(existing))) {
                throw new IllegalArgumentException("idempotency_payload_conflict");
            }
            return refreshJob(userId, token, existing);
        }
        String op = "synthesize";
        OfficialTtsPriceGate.Frozen frozen = prices.require(op, OfficialTtsPriceGate.MODEL, OfficialTtsPriceGate.REGION,
                "weighted_character");
        String text = String.valueOf(body.getOrDefault("text", "")).trim();
        if (text.isEmpty()) {
            throw new IllegalArgumentException("text_required");
        }
        OfficialTtsJobEntity job = new OfficialTtsJobEntity();
        job.setUserId(userId);
        job.setJobType(jobType);
        job.setStatus("running");
        job.setVoiceCode(voice);
        job.setRequestJson(canonical);
        job.setSynthesisText(text);
        job.setIdempotencyKey(idem);
        job.setSalePriceVersion(frozen.version);
        job.setOfficialCostVersion(frozen.version);
        job.setCreatedAt(new Date());
        job.setUpdatedAt(new Date());
        job.setStatus("queued");
        store.saveJob(job);
        Map<String, Object> gwBody = new HashMap<>();
        gwBody.put("model", OfficialTtsPriceGate.MODEL);
        gwBody.put("voice", voice);
        gwBody.put("text", text);
        gwBody.put("format", String.valueOf(body.getOrDefault("format", "wav")));
        gwBody.put("sample_rate", 16000);
        gwBody.put("operation", op);
        if (body.containsKey("volume")) {
            gwBody.put("volume", body.get("volume"));
        }
        if (body.containsKey("rate")) {
            gwBody.put("rate", body.get("rate"));
        }
        if (body.containsKey("pitch")) {
            gwBody.put("pitch", body.get("pitch"));
        }
        if (body.get("instruction") != null) {
            gwBody.put("instruction", body.get("instruction"));
        }
        // 方言：官方通过 instruction「请用X表达」控制；前端也可直接传 instruction
        Object dialectObj = body.get("dialect");
        if (dialectObj != null) {
            String dialect = String.valueOf(dialectObj).trim();
            if (!dialect.isEmpty() && !"普通话".equals(dialect) && !"Mandarin".equalsIgnoreCase(dialect)) {
                String existingInst = gwBody.get("instruction") == null ? "" : String.valueOf(gwBody.get("instruction"));
                if (!existingInst.contains(dialect)) {
                    String merged = ("请用" + dialect + "表达。" + existingInst).trim();
                    if (merged.length() > 100) {
                        merged = merged.substring(0, 100);
                    }
                    gwBody.put("instruction", merged);
                }
            }
        }
        if (body.get("languageHints") != null || body.get("language_hints") != null) {
            Object hints = body.get("languageHints") != null ? body.get("languageHints") : body.get("language_hints");
            gwBody.put("language_hints", hints instanceof List<?> ? hints : List.of(String.valueOf(hints)));
        }
        if (body.get("hotFix") != null || body.get("hot_fix") != null) {
            gwBody.put("hot_fix", OfficialHotFix.toOfficial(
                    body.get("hotFix") != null ? body.get("hotFix") : body.get("hot_fix")));
        }
        if (Boolean.TRUE.equals(body.get("enableAigcTag")) || Boolean.TRUE.equals(body.get("enable_aigc_tag"))) {
            gwBody.put("enable_aigc_tag", true);
            if (body.get("aigcPropagator") != null) {
                gwBody.put("aigc_propagator", body.get("aigcPropagator"));
            }
            if (body.get("aigc_propagator") != null) {
                gwBody.put("aigc_propagator", body.get("aigc_propagator"));
            }
            if (body.get("aigcPropagateId") != null) {
                gwBody.put("aigc_propagate_id", body.get("aigcPropagateId"));
            }
            if (body.get("aigc_propagate_id") != null) {
                gwBody.put("aigc_propagate_id", body.get("aigc_propagate_id"));
            }
        }
        if (body.get("enableSsml") != null || body.get("enable_ssml") != null) {
            gwBody.put("enable_ssml", body.get("enableSsml") != null ? body.get("enableSsml") : body.get("enable_ssml"));
        }
        if (body.get("bitRate") != null || body.get("bit_rate") != null) {
            Object brObj = body.get("bitRate") != null ? body.get("bitRate") : body.get("bit_rate");
            String fmt = String.valueOf(body.getOrDefault("format", "wav"));
            if (!"opus".equalsIgnoreCase(fmt)) {
                throw new IllegalArgumentException("bit_rate_format");
            }
            if (!(brObj instanceof Number n)) {
                throw new IllegalArgumentException("invalid_bit_rate");
            }
            int br = n.intValue();
            if (br < 6 || br > 510) {
                throw new IllegalArgumentException("invalid_bit_rate");
            }
            gwBody.put("bit_rate", br);
        }
        Map<String, Object> resp = gateway.synthesize(token, idem, gwBody);
        Number reserved = firstNumber(resp.get("reserved"), resp.get("quota"));
        Number settled = firstNumber(resp.get("settled"), null);
        long reservedVal = reserved == null ? 0L : reserved.longValue();
        long settledVal = settled == null ? 0L : settled.longValue();
        // Completed HTTP synth returns reserved=0 after settle; settled>0 still proves funds moved.
        if (reservedVal <= 0 && settledVal <= 0) {
            job.setStatus("failed");
            job.setErrorMsg("reservation_incomplete");
            store.saveJob(job);
            throw new IllegalStateException("quota_not_frozen");
        }
        job.setReservedQuota(reservedVal);
        job.setSettledQuota(settledVal);
        job.setBillId(str(resp.get("bill_id")));
        if (Boolean.TRUE.equals(resp.get("review"))) {
            job.setStatus("uncertain");
        } else if (resp.get("audio") != null) {
            byte[] audioBytes = OfficialTtsAudioInspector.normalizeWav(
                    Base64.getDecoder().decode(str(resp.get("audio"))));
            String format = String.valueOf(body.getOrDefault("format", "wav"));
            try {
                String ext = persistAudio(audioBytes, format);
                Files.createDirectories(root);
                Path dest = root.resolve("job-" + UUID.randomUUID() + ext);
                Files.write(dest, audioBytes);
                job.setResultPath(dest.toString());
                job.setStatus("done");
            } catch (Exception e) {
                job.setStatus("uncertain");
                job.setErrorMsg("audio_persist_failed:" + e.getMessage());
            }
        } else {
            job.setStatus("failed");
            job.setErrorMsg("no_audio");
        }
        store.saveJob(job);
        OfficialTtsLedgerEntity ledger = new OfficialTtsLedgerEntity();
        ledger.setUserId(userId);
        ledger.setJobId(job.getId());
        ledger.setPhase("done".equals(job.getStatus()) ? "settle" : ("uncertain".equals(job.getStatus()) ? "uncertain" : "reserve"));
        ledger.setQuota("done".equals(job.getStatus()) ? job.getSettledQuota() : job.getReservedQuota());
        ledger.setNote("gateway:" + job.getBillId() + ";reserved=" + job.getReservedQuota() + ";settled=" + job.getSettledQuota());
        store.saveLedger(ledger);
        return job;
    }

    public OfficialTtsJobEntity refreshJob(long userId, String token, OfficialTtsJobEntity job) {
        if (job == null || !Objects.equals(userId, job.getUserId())) {
            throw new IllegalArgumentException("job_not_found");
        }
        if ("done".equals(job.getStatus()) || "failed".equals(job.getStatus()) || "cancelled".equals(job.getStatus())) {
            return job;
        }
        if (job.getResultPath() != null) {
            return job;
        }
        if (token == null || job.getIdempotencyKey() == null) {
            return job;
        }
        try {
            Map<String, Object> gwBody = new HashMap<>();
            gwBody.put("model", OfficialTtsPriceGate.MODEL);
            gwBody.put("voice", job.getVoiceCode());
            gwBody.put("text", job.getSynthesisText());
            gwBody.put("format", "wav");
            Map<String, Object> resp = gateway.synthesize(token, job.getIdempotencyKey(), gwBody);
            if (resp.get("audio") != null) {
                byte[] audioBytes = OfficialTtsAudioInspector.normalizeWav(
                    Base64.getDecoder().decode(str(resp.get("audio"))));
                String ext = persistAudio(audioBytes, "wav");
                Files.createDirectories(root);
                Path dest = root.resolve("job-" + UUID.randomUUID() + ext);
                Files.write(dest, audioBytes);
                job.setResultPath(dest.toString());
                job.setStatus("done");
                Number settled = firstNumber(resp.get("settled"), resp.get("quota"));
                if (settled != null) {
                    job.setSettledQuota(settled.longValue());
                }
            } else if (Boolean.TRUE.equals(resp.get("review"))) {
                job.setStatus("uncertain");
            }
            store.saveJob(job);
        } catch (Exception e) {
            job.setStatus("uncertain");
            job.setErrorMsg("refresh_failed");
            store.saveJob(job);
        }
        return job;
    }

    public void cancelJob(long userId, String token, OfficialTtsJobEntity job) {
        if ("done".equals(job.getStatus())) {
            throw new IllegalStateException("job_already_done");
        }
        if (job.getBillId() != null) {
            Map<String, Object> resp = gateway.cancel(token, job.getBillId());
            job.setStatus("uncertain".equals(resp.get("status")) ? "uncertain" : "cancelled");
        } else {
            job.setStatus("cancelled");
        }
        if (job.getResultPath() != null) {
            try {
                Files.deleteIfExists(Path.of(job.getResultPath()));
            } catch (Exception ignored) {
            }
            job.setResultPath(null);
        }
        store.saveJob(job);
        OfficialTtsLedgerEntity ledger = new OfficialTtsLedgerEntity();
        ledger.setUserId(userId);
        ledger.setJobId(job.getId());
        ledger.setPhase("cancelled".equals(job.getStatus()) ? "release" : "uncertain");
        ledger.setQuota(job.getReservedQuota() == null ? 0L : job.getReservedQuota());
        ledger.setNote("cancel");
        store.saveLedger(ledger);
    }

    public byte[] downloadJob(long userId, OfficialTtsJobEntity job) {
        if (!Objects.equals(userId, job.getUserId()) || job.getResultPath() == null) {
            throw new IllegalArgumentException("download_forbidden");
        }
        try {
            return Files.readAllBytes(Path.of(job.getResultPath()));
        } catch (Exception e) {
            throw new IllegalStateException("download_failed", e);
        }
    }

    public byte[] serveMedia(String token) {
        long[] ids = OfficialTtsMediaToken.verify(mediaSecret, token);
        OfficialTtsAssetEntity asset = store.findAsset(ids[1]);
        if (asset == null || !Objects.equals(ids[0], asset.getUserId())) {
            throw new IllegalArgumentException("media_forbidden");
        }
        try {
            return Files.readAllBytes(Path.of(asset.getStoragePath()));
        } catch (Exception e) {
            throw new IllegalStateException("media_read_failed", e);
        }
    }

    private long applyGatewayVoice(OfficialTtsVoiceEntity row, Map<String, Object> resp,
            OfficialTtsPriceGate.Frozen frozen) {
        Number reserved = asNumber(resp.get("reserved"));
        Number settled = firstNumber(resp.get("settled"), resp.get("quota"));
        long reservedVal = reserved == null ? 0L : reserved.longValue();
        long settledVal = settled == null ? 0L : settled.longValue();
        row.setBillId(str(resp.get("bill_id")));
        String task = str(resp.get("task_id"));
        if (task != null && !task.isBlank()) {
            row.setErrorMsg("task:" + task);
        }
        String status = str(resp.get("status"));
        String upstreamErr = str(resp.get("error"));
        if ("failed".equals(status)) {
            row.setStatus("failed");
            row.setErrorMsg(upstreamErr == null || upstreamErr.isBlank() ? "upstream_failed" : upstreamErr);
            row.setUpdatedAt(new Date());
            return 0L;
        }
        if (reservedVal <= 0 && settledVal <= 0
                && !"uncertain".equals(status) && !Boolean.TRUE.equals(resp.get("review"))) {
            throw new IllegalStateException("quota_not_frozen");
        }
        long quotaVal = reservedVal > 0 ? reservedVal : settledVal;
        if ("available".equals(status)) {
            row.setStatus("available");
            row.setUpstreamVoiceId(str(resp.get("voice_id")));
        } else if ("uncertain".equals(status) || Boolean.TRUE.equals(resp.get("review"))) {
            row.setStatus("uncertain");
            if (upstreamErr != null && !upstreamErr.isBlank() && (row.getErrorMsg() == null || !row.getErrorMsg().startsWith("task:"))) {
                row.setErrorMsg(upstreamErr);
            }
        } else {
            row.setStatus("processing");
            if (resp.get("voice_id") != null) {
                row.setUpstreamVoiceId(str(resp.get("voice_id")));
            }
        }
        row.setUpdatedAt(new Date());
        return quotaVal;
    }

    private void persistDesignPreview(OfficialTtsVoiceEntity row, Map<String, Object> resp) {
        Object audio = resp.get("preview_audio");
        if (audio == null || row.getId() == null) {
            return;
        }
        String b64 = String.valueOf(audio).trim();
        if (b64.isEmpty() || "null".equals(b64)) {
            return;
        }
        try {
            byte[] bytes = OfficialTtsAudioInspector.normalizeWav(Base64.getDecoder().decode(b64));
            Files.createDirectories(root);
            Path dest = root.resolve("voice-preview-" + row.getId() + ".wav");
            Files.write(dest, bytes);
            row.setPreviewUrl(dest.toString());
            OfficialTtsAssetEntity asset = new OfficialTtsAssetEntity();
            asset.setUserId(row.getUserId());
            asset.setVoiceId(row.getId());
            asset.setPurpose("design_preview");
            asset.setStoragePath(dest.toString());
            asset.setMimeType("audio/wav");
            asset.setExpireAt(Date.from(Instant.now().plusSeconds(86400L * 30)));
            asset.setCreatedAt(new Date());
            store.saveAsset(asset);
        } catch (Exception ignored) {
            // preview is best-effort; voice row still usable
        }
    }

    /** DashScope voice prefix: letters/digits, max 10 chars. */
    private static String voicePrefix(long userId) {
        String tail = Long.toString(Math.floorMod(userId, 1_000_000_000L));
        return ("u" + tail).substring(0, Math.min(10, ("u" + tail).length()));
    }

    private void writeLedger(long userId, Long jobId, String phase, String billId, long quota) {
        OfficialTtsLedgerEntity ledger = new OfficialTtsLedgerEntity();
        ledger.setUserId(userId);
        ledger.setJobId(jobId);
        ledger.setPhase(phase);
        ledger.setQuota(quota);
        ledger.setNote("gateway:" + billId + ";phase=" + phase);
        store.saveLedger(ledger);
    }

    private static String canonical(String kind, Map<String, Object> body) {
        Map<String, Object> slim = new HashMap<>();
        slim.put("kind", kind);
        for (String k : List.of("name", "prompt", "previewText", "preview_text", "upstreamVoiceId", "languageHints",
                "jobType", "voice", "text", "format", "instruction", "dialect", "audioSha256", "volume", "rate", "pitch",
                "hotFix", "hot_fix", "enableAigcTag", "enable_aigc_tag", "enableSsml", "enable_ssml",
                "bitRate", "bit_rate", "language_hints")) {
            if (body.containsKey(k)) {
                slim.put(k, body.get(k));
            }
        }
        return xiaozhi.common.utils.JsonUtils.toJsonString(slim);
    }

    private static String hintsWithHash(Map<String, Object> body, String hash) {
        return String.valueOf(body.getOrDefault("languageHints", "zh")) + ";ph=" + hash;
    }

    private static String phash(OfficialTtsVoiceEntity row) {
        String h = row.getLanguageHints();
        int i = h == null ? -1 : h.indexOf(";ph=");
        return i >= 0 ? h.substring(i + 4) : "";
    }

    private static String phashJob(OfficialTtsJobEntity job) {
        return OfficialTtsVoiceAcl.payloadHash(job.getRequestJson() == null ? "" : job.getRequestJson());
    }

    private static String str(Object v) {
        return v == null ? null : String.valueOf(v);
    }

    private static String firstNonBlank(String a, String b) {
        return a != null && !a.isBlank() ? a : b;
    }

    private static Number firstNumber(Object a, Object b) {
        Number n = asNumber(a);
        return n != null ? n : asNumber(b);
    }

    private static String sha256Hex(byte[] data) {
        try {
            java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-256");
            byte[] d = md.digest(data);
            StringBuilder sb = new StringBuilder(64);
            for (byte b : d) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new IllegalStateException("sha256_unavailable", e);
        }
    }

    private static String persistAudio(byte[] audio, String format) {
        String fmt = format == null || format.isBlank() ? "wav" : format.toLowerCase();
        if ("wav".equals(fmt)) {
            OfficialTtsAudioInspector.inspectExportWav(audio);
            return ".wav";
        }
        if ("mp3".equals(fmt)) {
            boolean id3 = audio.length >= 3 && audio[0] == 'I' && audio[1] == 'D' && audio[2] == '3';
            boolean frame = audio.length >= 2 && audio[0] == (byte) 0xFF && (audio[1] & 0xE0) == 0xE0;
            if (!id3 && !frame) {
                throw new IllegalArgumentException("audio_not_mp3");
            }
            return ".mp3";
        }
        if ("opus".equals(fmt) || "ogg".equals(fmt)) {
            boolean ogg = audio.length >= 4 && audio[0] == 'O' && audio[1] == 'g' && audio[2] == 'g' && audio[3] == 'S';
            if (!ogg) {
                throw new IllegalArgumentException("audio_not_opus");
            }
            return ".opus";
        }
        if ("pcm".equals(fmt)) {
            if (audio.length < 2) {
                throw new IllegalArgumentException("audio_not_pcm");
            }
            return ".pcm";
        }
        throw new IllegalArgumentException("unsupported_export_format");
    }

    private static Number asNumber(Object v) {
        if (v instanceof Number n) {
            return n;
        }
        return null;
    }

    public interface Store {
        OfficialTtsVoiceEntity findVoiceByIdem(long userId, String idem);

        void saveVoice(OfficialTtsVoiceEntity row);

        OfficialTtsJobEntity findJobByIdem(long userId, String idem);

        void saveJob(OfficialTtsJobEntity row);

        void saveAsset(OfficialTtsAssetEntity row);

        OfficialTtsAssetEntity findAsset(long id);

        void saveLedger(OfficialTtsLedgerEntity row);
    }

    public static final class MemoryStore implements Store {
        public final ConcurrentHashMap<String, OfficialTtsVoiceEntity> voices = new ConcurrentHashMap<>();
        public final ConcurrentHashMap<String, OfficialTtsJobEntity> jobs = new ConcurrentHashMap<>();
        public final ConcurrentHashMap<Long, OfficialTtsAssetEntity> assets = new ConcurrentHashMap<>();
        public final ConcurrentHashMap<Long, OfficialTtsLedgerEntity> ledgers = new ConcurrentHashMap<>();
        private final AtomicLong ids = new AtomicLong(1);
        private final AtomicLong ledgerId = new AtomicLong(1);

        @Override
        public OfficialTtsVoiceEntity findVoiceByIdem(long userId, String idem) {
            return voices.get(userId + ":" + idem);
        }

        @Override
        public void saveVoice(OfficialTtsVoiceEntity row) {
            if (row.getId() == null) {
                row.setId(ids.getAndIncrement());
            }
            voices.put(row.getUserId() + ":" + row.getIdempotencyKey(), row);
        }

        @Override
        public OfficialTtsJobEntity findJobByIdem(long userId, String idem) {
            return jobs.get(userId + ":" + idem);
        }

        @Override
        public void saveJob(OfficialTtsJobEntity row) {
            if (row.getId() == null) {
                row.setId(ids.getAndIncrement());
            }
            jobs.put(row.getUserId() + ":" + row.getIdempotencyKey(), row);
        }

        @Override
        public void saveAsset(OfficialTtsAssetEntity row) {
            if (row.getId() == null) {
                row.setId(ids.getAndIncrement());
            }
            assets.put(row.getId(), row);
        }

        @Override
        public OfficialTtsAssetEntity findAsset(long id) {
            return assets.get(id);
        }

        @Override
        public void saveLedger(OfficialTtsLedgerEntity row) {
            if (row.getId() == null) {
                row.setId(ledgerId.getAndIncrement());
            }
            ledgers.put(row.getId(), row);
        }
    }
}
