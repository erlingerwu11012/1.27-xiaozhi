package xiaozhi.modules.officialtts.service.impl;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;

import lombok.RequiredArgsConstructor;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.utils.JsonUtils;
import xiaozhi.modules.agent.dao.AgentDao;
import xiaozhi.modules.agent.entity.AgentEntity;
import xiaozhi.modules.agent.service.AgentService;
import xiaozhi.modules.model.OfficialServiceDefaults;
import xiaozhi.modules.officialtts.dao.OfficialTtsAssetDao;
import xiaozhi.modules.officialtts.dao.OfficialTtsAuditDao;
import xiaozhi.modules.officialtts.dao.OfficialTtsJobDao;
import xiaozhi.modules.officialtts.dao.OfficialTtsLedgerDao;
import xiaozhi.modules.officialtts.dao.OfficialTtsPriceDao;
import xiaozhi.modules.officialtts.dao.OfficialTtsVoiceDao;
import xiaozhi.modules.officialtts.entity.OfficialTtsAssetEntity;
import xiaozhi.modules.officialtts.entity.OfficialTtsAuditEntity;
import xiaozhi.modules.officialtts.entity.OfficialTtsJobEntity;
import xiaozhi.modules.officialtts.entity.OfficialTtsLedgerEntity;
import xiaozhi.modules.officialtts.entity.OfficialTtsPriceEntity;
import xiaozhi.modules.officialtts.entity.OfficialTtsVoiceEntity;
import xiaozhi.modules.officialtts.engine.OfficialTtsEngine;
import xiaozhi.modules.officialtts.engine.OfficialTtsGatewayClient;
import xiaozhi.modules.officialtts.engine.OfficialTtsPriceGate;
import xiaozhi.modules.officialtts.engine.OfficialTtsPriceLifecycle;
import xiaozhi.modules.officialtts.engine.OfficialTtsSettlePolicy;
import xiaozhi.modules.officialtts.engine.OfficialTtsVoiceAcl;
import xiaozhi.modules.officialtts.service.OfficialTtsService;
import xiaozhi.modules.pay.constant.PayConstants;
import xiaozhi.modules.pay.dao.OneApiProvisioningDao;
import xiaozhi.modules.pay.service.OneApiBindingService;
import xiaozhi.modules.pay.vo.OneApiDeviceTokenVO;
import xiaozhi.modules.security.user.SecurityUser;
import xiaozhi.modules.sys.service.SysParamsService;

@Service
@RequiredArgsConstructor
public class OfficialTtsServiceImpl implements OfficialTtsService {
    private static final long MIN_FREE_BYTES = 512L * 1024 * 1024;
    private static final Path ROOT = Paths.get("uploads/official-tts");

    private final OfficialTtsVoiceDao voiceDao;
    private final OfficialTtsAssetDao assetDao;
    private final OfficialTtsJobDao jobDao;
    private final OfficialTtsPriceDao priceDao;
    private final OfficialTtsLedgerDao ledgerDao;
    private final OfficialTtsAuditDao auditDao;
    private final AgentService agentService;
    private final AgentDao agentDao;
    private final SysParamsService sysParamsService;
    private final OneApiProvisioningDao oneApiProvisioningDao;
    private final OneApiBindingService oneApiBindingService;

    public boolean enhancedEnabledFor(Long userId) {
        String mode = enhancedMode();
        if ("off".equals(mode)) {
            return false;
        }
        if ("open".equals(mode)) {
            // Master kill-switch must be true; empty allowlist must NOT imply open.
            return masterKillEnabled() && userId != null;
        }
        // allowlist (default when mode unset and enabled=false legacy)
        if ("allowlist".equals(mode)) {
            if (modeParamPresent() && !masterKillEnabled()) {
                return false;
            }
            return isAllowlisted(userId);
        }
        return false;
    }

    /** Resolved access mode: off | allowlist | open. */
    public String enhancedMode() {
        String explicit = StringUtils.trimToEmpty(sysParamsService.getValue("official.tts.enhanced.mode", true));
        if (StringUtils.isNotBlank(explicit)) {
            String m = explicit.toLowerCase();
            if ("off".equals(m) || "allowlist".equals(m) || "open".equals(m)) {
                return m;
            }
            return "off";
        }
        // Legacy (no mode param): enabled=true meant open-all; else allowlist.
        return masterKillEnabled() ? "open" : "allowlist";
    }

    private boolean modeParamPresent() {
        return StringUtils.isNotBlank(StringUtils.trimToEmpty(
                sysParamsService.getValue("official.tts.enhanced.mode", true)));
    }

    private boolean masterKillEnabled() {
        return "true".equalsIgnoreCase(StringUtils.trimToEmpty(
                sysParamsService.getValue("official.tts.enhanced.enabled", true)));
    }

    private boolean isAllowlisted(Long userId) {
        String allow = sysParamsService.getValue("official.tts.enhanced.allow_users", true);
        if (StringUtils.isBlank(allow) || userId == null) {
            return false;
        }
        for (String part : allow.split(",")) {
            if (userId.toString().equals(part.trim())) {
                return true;
            }
        }
        return false;
    }

    public boolean pricingReady() {
        return pricingReadyFor("preview") && pricingReadyFor("synthesize");
    }

    public boolean pricingReadyFor(String operation) {
        try {
            OfficialTtsPriceGate gate = priceGate();
            if ("preview".equals(operation) || "synthesize".equals(operation)) {
                gate.require(operation, OfficialTtsPriceGate.MODEL, OfficialTtsPriceGate.REGION, "weighted_character");
                return true;
            }
            if ("clone".equals(operation) || "design".equals(operation)) {
                gate.require(operation, OfficialTtsPriceGate.MODEL, OfficialTtsPriceGate.REGION, "count");
                return true;
            }
            return false;
        } catch (RuntimeException e) {
            return false;
        }
    }

    private OfficialTtsPriceGate priceGate() {
        List<OfficialTtsPriceEntity> rows = priceDao.selectList(null);
        java.util.ArrayList<OfficialTtsPriceGate.Row> mapped = new java.util.ArrayList<>();
        if (rows != null) {
            for (OfficialTtsPriceEntity p : rows) {
                mapped.add(new OfficialTtsPriceGate.Row(p.getPriceKind(), p.getOperation(), p.getVersion(), p.getUnit(),
                        p.getAmount(), p.getStatus()));
            }
        }
        return new OfficialTtsPriceGate(mapped);
    }

    @Override
    public Map<String, Object> capabilities(Long userId) {
        Map<String, Object> data = new HashMap<>();
        data.put("model", OfficialServiceDefaults.TTS_MODEL_NAME);
        data.put("officialModelId", OfficialServiceDefaults.TTS_MODEL_ID);
        data.put("displayName", OfficialServiceDefaults.DISPLAY_NAME);
        data.put("streaming", "duplex");
        data.put("submitMode", "sentence_unit_once");
        data.put("excluded", List.of("seed", "word_timestamp_enabled"));
        data.put("verifiedVoices", List.of(
                Map.of("code", "longanlingxi", "name", "龙安灵汐", "verified", true, "languages", List.of("zh", "en")),
                Map.of("code", "longanqian", "name", "龙安千", "verified", true, "languages", List.of("zh", "en"))));
        boolean access = enhancedEnabledFor(userId);
        String mode = enhancedMode();
        boolean synthPriced = pricingReady();
        boolean clonePriced = pricingReadyFor("clone");
        boolean designPriced = pricingReadyFor("design");
        data.put("enhancedMode", mode);
        data.put("enhancedMasterEnabled", masterKillEnabled());
        data.put("enhancedEnabled", access);
        data.put("pricingStatus", synthPriced ? "configured" : "pricing_pending");
        data.put("customerCallable", access && synthPriced);
        data.put("accessStatus", resolveAccessStatus(userId, access, synthPriced));
        data.put("accessStatusText", accessStatusText(resolveAccessStatus(userId, access, synthPriced)));
        Map<String, Object> ops = new HashMap<>();
        ops.put("preview", opCap(access, pricingReadyFor("preview")));
        ops.put("synthesize", opCap(access, pricingReadyFor("synthesize")));
        ops.put("clone", opCap(access, clonePriced));
        ops.put("design", opCap(access, designPriced));
        data.put("operations", ops);
        data.put("controlTags", List.of(
                "sad", "amazed", "deep and loud shouting", "trembling", "angry", "excited",
                "sarcastic", "curious", "like dracula", "bored", "tired", "scornful",
                "shouting", "asmr", "panicked", "mischievously", "empathetic", "whispers",
                "reluctantly", "crying", "serious", "very slowly", "very fast"));
        data.put("actionTags", List.of(
                "gasp", "sighing", "clears throat", "giggles", "laughing", "cough", "snorts"));
        data.put("formatsExport", List.of("wav", "mp3", "pcm", "opus"));
        data.put("formatsDevice", List.of("pcm"));
        data.put("volume", Map.of("min", 0, "max", 100, "default", 50));
        data.put("rate", Map.of("min", 0.5, "max", 2.0, "default", 1.0));
        data.put("pitch", Map.of("min", 0.5, "max", 2.0, "default", 1.0));
        data.put("languageHints", List.of(
                "zh", "en", "ja", "ko", "ru", "fr", "de", "pt", "th", "id", "vi", "es", "it", "ms", "fil", "ar"));
        data.put("dialectsVerified", List.of(
                "普通话", "广东话", "重庆话", "东北话", "甘肃话", "贵州话", "浙江话", "河北话", "河南话",
                "湖北话", "湖南话", "江西话", "宁波话", "宁夏话", "青岛话", "陕西话", "山西话", "山东话",
                "上海话", "四川话", "云南话"));
        data.put("dialectVia", "instruction");
        data.put("instructionMaxChars", 100);
        data.put("bitRate", Map.of(
                "unit", "kbps",
                "min", 6,
                "max", 510,
                "formats", List.of("opus"),
                "note", "Aliyun HTTP CosyVoice: kbps, opus only. Device PCM playback does not send bit_rate."));
        data.put("hotFix", Map.of(
                "official", Map.of(
                        "replace", List.of(Map.of("啊", "你好世界")),
                        "pronunciation", List.of(Map.of("天气", "tian1 qi4"))),
                "platformSimplified", "object-of-strings is converted server-side to replace[]"));
        data.put("unsupported", List.of("seed", "word_timestamp_enabled", "ssml_unverified", "hot_word_unverified"));
        return data;
    }

    private Map<String, Object> opCap(boolean access, boolean priced) {
        Map<String, Object> m = new HashMap<>();
        m.put("access", access);
        m.put("priced", priced);
        m.put("callable", access && priced);
        return m;
    }

    private String resolveAccessStatus(Long userId, boolean access, boolean synthPriced) {
        if ("off".equals(enhancedMode())) {
            return "disabled";
        }
        if (modeParamPresent() && !masterKillEnabled()) {
            return "disabled";
        }
        if (!modeParamPresent() && !masterKillEnabled() && !access) {
            return "disabled";
        }
        if (!access) {
            return "account_not_allowed";
        }
        if (!synthPriced) {
            return "pricing_pending";
        }
        return "ready";
    }

    private String accessStatusText(String status) {
        switch (status) {
            case "disabled":
                return "官方语音增强未启用";
            case "account_not_allowed":
                return "当前账号未开放官方语音增强";
            case "pricing_pending":
                return "官方语音尚未配置有效售价";
            case "insufficient_quota":
                return "余额不足";
            case "model_unauthorized":
                return "模型或操作未授权";
            case "ready":
                return "可使用";
            default:
                return "当前不可用";
        }
    }

    @Override
    public OfficialTtsVoiceEntity createVoice(Long userId, String idempotencyKey, Map<String, Object> body,
            MultipartFile audio) {
        requireEnhanced(userId);
        byte[] bytes = null;
        if (audio != null && !audio.isEmpty()) {
            try {
                bytes = audio.getBytes();
            } catch (IOException e) {
                throw new RenException("读取上传失败");
            }
        }
        try {
            return engine().createVoice(userId, requireToken(userId), idempotencyKey, body == null ? Map.of() : body, bytes);
        } catch (IllegalArgumentException | IllegalStateException e) {
            throw new RenException(e.getMessage());
        }
    }

    @Override
    public List<OfficialTtsVoiceEntity> listVoices(Long userId) {
        List<OfficialTtsVoiceEntity> rows = voiceDao.selectList(new LambdaQueryWrapper<OfficialTtsVoiceEntity>()
                .eq(OfficialTtsVoiceEntity::getUserId, userId)
                .ne(OfficialTtsVoiceEntity::getStatus, "deleted")
                .orderByDesc(OfficialTtsVoiceEntity::getId));
        String token = null;
        try {
            token = requireToken(userId);
        } catch (RuntimeException ignored) {
            // list still works without refresh
        }
        OfficialTtsEngine eng = null;
        try {
            eng = engine();
        } catch (RuntimeException ignored) {
        }
        boolean previewBackfilled = false;
        for (OfficialTtsVoiceEntity row : rows) {
            if (eng != null && token != null
                    && ("processing".equals(row.getStatus()) || "uncertain".equals(row.getStatus()))) {
                try {
                    eng.refreshVoice(userId, token, row);
                } catch (RuntimeException ignored) {
                }
            }
            if (eng != null && !previewBackfilled && token != null && "available".equals(row.getStatus())
                    && !eng.hasVoicePreview(row)) {
                // 每次列表最多补一条试听音频，避免单个请求串行合成多条阻塞页面
                previewBackfilled = true;
                try {
                    eng.ensureVoicePreview(userId, token, row);
                } catch (RuntimeException ignored) {
                }
            }
            if (eng != null) {
                row.setHasPreview(eng.hasVoicePreview(row));
            } else {
                row.setHasPreview(false);
            }
        }
        return rows;
    }

    @Override
    public OfficialTtsVoiceEntity getVoice(Long userId, Long id) {
        OfficialTtsVoiceEntity row = voiceDao.selectById(id);
        if (row == null || !userId.equals(row.getUserId())) {
            throw new RenException("音色不存在");
        }
        try {
            OfficialTtsVoiceEntity refreshed = engine().refreshVoice(userId, requireToken(userId), row);
            refreshed.setHasPreview(engine().hasVoicePreview(refreshed));
            return refreshed;
        } catch (RuntimeException e) {
            row.setHasPreview(false);
            try {
                row.setHasPreview(engine().hasVoicePreview(row));
            } catch (RuntimeException ignored) {
            }
            return row;
        }
    }

    @Override
    public OfficialTtsVoiceEntity renameVoice(Long userId, Long id, String name) {
        OfficialTtsVoiceEntity row = getVoice(userId, id);
        String trimmed = name == null ? "" : name.trim();
        if (trimmed.isEmpty()) {
            throw new RenException("名称不能为空");
        }
        if (trimmed.length() > 64) {
            trimmed = trimmed.substring(0, 64);
        }
        row.setName(trimmed);
        row.setUpdatedAt(new java.util.Date());
        voiceDao.updateById(row);
        return row;
    }

    @Override
    public void deleteVoice(Long userId, Long id) {
        OfficialTtsVoiceEntity row = getVoice(userId, id);
        try {
            engine().deleteVoice(userId, requireToken(userId), row, isVoiceBound(userId, row));
            audit(userId, userId, "delete_voice", "voice", String.valueOf(id), row.getStatus());
        } catch (IllegalArgumentException | IllegalStateException e) {
            throw new RenException(e.getMessage());
        }
    }

    @Override
    public OfficialTtsVoiceEntity bindVoice(Long userId, Long voiceId, String agentId) {
        requireEnhanced(userId);
        OfficialTtsVoiceEntity row = getVoice(userId, voiceId);
        if (!"available".equals(row.getStatus())) {
            throw new RenException("仅可用且归属校验通过的音色可绑定");
        }
        OfficialTtsVoiceAcl.require(row.getUpstreamVoiceId(), allowedVoiceCodes(userId));
        AgentEntity agent = requireAgent(userId, agentId);
        if (!OfficialServiceDefaults.isOfficialTts(agent.getTtsModelId())) {
            throw new RenException("仅官方TTS智能体可绑定官方音色");
        }
        Map<String, Object> binding = new HashMap<>();
        binding.put("voice", row.getUpstreamVoiceId());
        binding.put("voice_kind", row.getKind());
        binding.put("voice_status", "available");
        agent.setOfficialTtsJson(JsonUtils.toJsonString(binding));
        if (StringUtils.isNotBlank(row.getUpstreamVoiceId())) {
            agent.setTtsVoiceId(row.getUpstreamVoiceId());
        }
        agentService.updateById(agent);
        row.setAgentId(agentId);
        voiceDao.updateById(row);
        audit(userId, userId, "bind_voice", "voice", String.valueOf(voiceId), agentId);
        return row;
    }

    @Override
    public OfficialTtsJobEntity createJob(Long userId, String idempotencyKey, Map<String, Object> body) {
        requireEnhanced(userId);
        try {
            OfficialTtsJobEntity job = engine().createJob(userId, requireToken(userId), idempotencyKey,
                    body == null ? Map.of() : body, allowedVoiceCodes(userId));
            audit(userId, userId, "create_job", "job", String.valueOf(job.getId()), job.getJobType());
            return job;
        } catch (IllegalArgumentException | IllegalStateException e) {
            throw new RenException(e.getMessage());
        }
    }

    @Override
    public OfficialTtsJobEntity getJob(Long userId, Long id) {
        OfficialTtsJobEntity job = jobDao.selectById(id);
        if (job == null || !userId.equals(job.getUserId())) {
            throw new RenException("任务不存在");
        }
        return job;
    }

    @Override
    public List<OfficialTtsJobEntity> listJobs(Long userId) {
        return jobDao.selectList(new LambdaQueryWrapper<OfficialTtsJobEntity>()
                .eq(OfficialTtsJobEntity::getUserId, userId)
                .orderByDesc(OfficialTtsJobEntity::getId));
    }

    @Override
    public void cancelJob(Long userId, Long id) {
        OfficialTtsJobEntity job = getJob(userId, id);
        try {
            engine().cancelJob(userId, requireToken(userId), job);
        } catch (IllegalArgumentException | IllegalStateException e) {
            throw new RenException(e.getMessage());
        }
    }

    @Override
    public void deleteJob(Long userId, Long id) {
        OfficialTtsJobEntity job = getJob(userId, id);
        // 未完成任务先尝试取消账单；已完成仅删本地资产（不计费回退）
        if (!"done".equals(job.getStatus()) && !"cancelled".equals(job.getStatus())) {
            try {
                engine().cancelJob(userId, requireToken(userId), job);
            } catch (Exception ignored) {
                // 继续本地删除，避免用户卡在列表里
            }
        }
        if (job.getResultPath() != null && !job.getResultPath().isBlank()) {
            try {
                java.nio.file.Files.deleteIfExists(java.nio.file.Path.of(job.getResultPath()));
            } catch (Exception ignored) {
            }
        }
        jobDao.deleteById(id);
        audit(userId, userId, "delete_job", "job", String.valueOf(id), job.getStatus());
    }

    @Override
    public byte[] downloadJob(Long userId, Long id) {
        OfficialTtsJobEntity job = getJob(userId, id);
        try {
            return engine().downloadJob(userId, job);
        } catch (IllegalArgumentException | IllegalStateException e) {
            throw new RenException(e.getMessage());
        }
    }

    @Override
    public byte[] downloadVoicePreview(Long userId, Long id) {
        OfficialTtsVoiceEntity row = getVoice(userId, id);
        try {
            return engine().downloadVoicePreview(userId, row);
        } catch (IllegalArgumentException | IllegalStateException e) {
            throw new RenException(e.getMessage());
        }
    }

    @Override
    public byte[] ensureVoicePreview(Long userId, Long id) {
        OfficialTtsVoiceEntity row = getVoice(userId, id);
        if (!engine().hasVoicePreview(row)) {
            if (!"available".equals(row.getStatus())) {
                throw new RenException("音色尚未就绪，暂时无法试听");
            }
            if (row.getUpstreamVoiceId() == null || row.getUpstreamVoiceId().isBlank()) {
                throw new RenException("音色缺少上游标识，无法试听");
            }
            String token;
            try {
                token = requireToken(userId);
            } catch (RuntimeException e) {
                throw new RenException("缺少调用凭证，请重新登录后再试");
            }
            // 用户主动点击 -> 忽略冷却期，务必真正尝试一次
            if (!engine().ensureVoicePreview(userId, token, row, true)) {
                throw new RenException("试听音频生成失败，请稍后重试");
            }
            row = getVoice(userId, id);
        }
        try {
            return engine().downloadVoicePreview(userId, row);
        } catch (IllegalArgumentException | IllegalStateException e) {
            throw new RenException(e.getMessage());
        }
    }

    @Override
    public Map<String, Object> adminOverview() {
        Map<String, Object> data = new HashMap<>();
        Map<String, String> gwEnabled = new HashMap<>();
        try {
            Map<String, Object> published = engine().gateway.publishedPrices(adminToken());
            Object rows = published.get("prices");
            if (rows instanceof List<?> list) {
                for (Object row : list) {
                    if (!(row instanceof Map<?, ?> m)) {
                        continue;
                    }
                    boolean enabled = Boolean.TRUE.equals(m.get("enabled"))
                            || "true".equals(String.valueOf(m.get("enabled")));
                    if (enabled) {
                        gwEnabled.put(String.valueOf(m.get("operation")), String.valueOf(m.get("version")));
                    }
                }
            }
        } catch (RuntimeException ignored) {
            data.put("gatewayPublishedError", true);
        }
        List<OfficialTtsPriceEntity> prices = priceDao.selectList(null);
        for (OfficialTtsPriceEntity price : prices) {
            price.setLifecycleStatus(OfficialTtsPriceLifecycle.classify(price.getStatus(), price.getVersion(),
                    gwEnabled.get(price.getOperation())));
        }
        data.put("prices", prices);
        data.put("gatewayEnabledByOperation", gwEnabled);
        data.put("priceUnitHintSale", OfficialTtsPriceLifecycle.UNIT_HINT_SALE);
        data.put("priceUnitHintCost", OfficialTtsPriceLifecycle.UNIT_HINT_COST);
        data.put("voices", voiceDao.selectCount(null));
        data.put("jobs", jobDao.selectCount(null));
        data.put("uncertainLedgers", ledgerDao.selectCount(new LambdaQueryWrapper<OfficialTtsLedgerEntity>()
                .eq(OfficialTtsLedgerEntity::getPhase, "uncertain")));
        data.put("enhancedFlag", sysParamsService.getValue("official.tts.enhanced.enabled", true));
        data.put("enhancedMode", enhancedMode());
        data.put("allowUsers", sysParamsService.getValue("official.tts.enhanced.allow_users", true));
        data.put("pricingReadySynth", pricingReady());
        data.put("pricingReadyClone", pricingReadyFor("clone"));
        data.put("pricingReadyDesign", pricingReadyFor("design"));
        data.put("audits", auditDao.selectList(new LambdaQueryWrapper<OfficialTtsAuditEntity>()
                .orderByDesc(OfficialTtsAuditEntity::getId).last("LIMIT 50")));
        return data;
    }

    @Override
    public int syncDeviceTokenModels() {
        return oneApiProvisioningDao.updateModelsByName(
                PayConstants.ONEAPI_DEVICE_TOKEN_NAME, PayConstants.ONEAPI_DEVICE_TOKEN_MODELS);
    }

    @Override
    public OfficialTtsPriceEntity updatePrice(OfficialTtsPriceEntity price) {
        if (price == null || StringUtils.isBlank(price.getOperation()) || StringUtils.isBlank(price.getUnit())) {
            throw new RenException("price_identity_required");
        }
        if (StringUtils.isBlank(price.getPriceKind())) {
            price.setPriceKind("sale_points");
        }
        if (!"sale_points".equals(price.getPriceKind())) {
            if (price.getId() == null) {
                if (StringUtils.isBlank(price.getStatus())) {
                    price.setStatus(OfficialTtsPriceLifecycle.COST_PENDING);
                }
                if (price.getCreatedAt() == null) {
                    price.setCreatedAt(new Date());
                }
                priceDao.insert(price);
                return price;
            }
            OfficialTtsPriceEntity existing = priceDao.selectById(price.getId());
            if (existing == null) {
                throw new RenException("price_not_found");
            }
            existing.setAmount(price.getAmount());
            priceDao.updateById(existing);
            return existing;
        }
        if (price.getId() != null) {
            OfficialTtsPriceEntity existing = priceDao.selectById(price.getId());
            if (existing == null) {
                throw new RenException("price_not_found");
            }
            try {
                OfficialTtsPriceLifecycle.assertDraftMutable(existing.getStatus());
            } catch (IllegalStateException e) {
                throw new RenException("published_immutable");
            }
            existing.setAmount(price.getAmount());
            existing.setUnit(price.getUnit());
            existing.setStatus(OfficialTtsPriceLifecycle.DRAFT);
            priceDao.updateById(existing);
            return existing;
        }
        List<OfficialTtsPriceEntity> rows = priceDao.selectList(new LambdaQueryWrapper<OfficialTtsPriceEntity>()
                .eq(OfficialTtsPriceEntity::getPriceKind, "sale_points")
                .eq(OfficialTtsPriceEntity::getOperation, price.getOperation()));
        List<String> versions = new java.util.ArrayList<>();
        for (OfficialTtsPriceEntity row : rows) {
            versions.add(row.getVersion());
        }
        if (StringUtils.isBlank(price.getVersion())) {
            price.setVersion(OfficialTtsPriceLifecycle.nextVersion(OfficialTtsPriceGate.MODEL,
                    OfficialTtsPriceGate.REGION, versions));
        } else if (versions.contains(price.getVersion())) {
            throw new RenException("price_version_duplicate");
        }
        price.setStatus(OfficialTtsPriceLifecycle.DRAFT);
        if (price.getCreatedAt() == null) {
            price.setCreatedAt(new Date());
        }
        priceDao.insert(price);
        return price;
    }

    @Override
    public OfficialTtsPriceEntity draftFromPublished(Long id) {
        OfficialTtsPriceEntity src = priceDao.selectById(id);
        if (src == null) {
            throw new RenException("price_not_found");
        }
        if (!"sale_points".equals(src.getPriceKind())) {
            throw new RenException("cost_price_not_publishable");
        }
        List<OfficialTtsPriceEntity> rows = priceDao.selectList(new LambdaQueryWrapper<OfficialTtsPriceEntity>()
                .eq(OfficialTtsPriceEntity::getPriceKind, "sale_points")
                .eq(OfficialTtsPriceEntity::getOperation, src.getOperation()));
        List<String> versions = new java.util.ArrayList<>();
        for (OfficialTtsPriceEntity row : rows) {
            versions.add(row.getVersion());
        }
        OfficialTtsPriceEntity draft = new OfficialTtsPriceEntity();
        draft.setPriceKind("sale_points");
        draft.setOperation(src.getOperation());
        draft.setUnit(src.getUnit());
        draft.setAmount(src.getAmount());
        draft.setVersion(OfficialTtsPriceLifecycle.nextVersion(OfficialTtsPriceGate.MODEL, OfficialTtsPriceGate.REGION,
                versions));
        draft.setStatus(OfficialTtsPriceLifecycle.DRAFT);
        draft.setCreatedAt(new Date());
        priceDao.insert(draft);
        return draft;
    }

    @Override
    public OfficialTtsPriceEntity publishPrice(Long id, String reason) {
        OfficialTtsPriceEntity price = priceDao.selectById(id);
        if (price == null) {
            throw new RenException("price_not_found");
        }
        if (!"sale_points".equals(price.getPriceKind())) {
            throw new RenException("cost_price_not_publishable");
        }
        if (OfficialTtsPriceLifecycle.HISTORY.equals(price.getStatus())) {
            throw new RenException("published_immutable");
        }
        if (price.getAmount() == null || price.getAmount().signum() < 0) {
            throw new RenException("sale_amount_required");
        }
        if (StringUtils.isBlank(price.getVersion()) || !price.getVersion().contains("|")) {
            throw new RenException("version_must_be_model_region_id");
        }
        String adminToken = sysParamsService.getValue("official.tts.admin.token", true);
        if (StringUtils.isBlank(adminToken)) {
            throw new RenException("admin_settle_token_required");
        }
        String chargeMode = chargeModeOf(price.getOperation());
        Map<String, Object> spec = new HashMap<>();
        spec.put("model", OfficialTtsPriceGate.MODEL);
        spec.put("region", OfficialTtsPriceGate.REGION);
        spec.put("operation", price.getOperation());
        spec.put("unit", price.getUnit());
        spec.put("version", price.getVersion());
        spec.put("charge_mode", chargeMode);
        spec.put("cny_per_unit", price.getAmount().toPlainString());
        spec.put("reason", StringUtils.defaultIfBlank(reason, "admin_publish"));
        Map<String, Object> body = new HashMap<>();
        body.put("reason", spec.get("reason"));
        body.put("prices", List.of(spec));
        Map<String, Object> ack;
        try {
            ack = engine().gateway.publishPrices(adminToken, body);
        } catch (RuntimeException e) {
            price.setStatus(OfficialTtsPriceLifecycle.ACK_PENDING);
            priceDao.updateById(price);
            throw new RenException("发布失败或响应丢失，未改当前生效版本，请查询网关后同步: " + e.getMessage());
        }
        if (!Boolean.TRUE.equals(ack.get("ack")) && !"published".equals(String.valueOf(ack.get("status")))) {
            price.setStatus(OfficialTtsPriceLifecycle.FAILED);
            priceDao.updateById(price);
            throw new RenException("发布失败，网关未确认，仍使用原生效版本");
        }
        Object versions = ack.get("versions");
        boolean matched = false;
        if (versions instanceof List<?>) {
            for (Object v : (List<?>) versions) {
                if (price.getVersion().equals(String.valueOf(v))) {
                    matched = true;
                    break;
                }
            }
        }
        if (!matched) {
            price.setStatus(OfficialTtsPriceLifecycle.ACK_PENDING);
            priceDao.updateById(price);
            throw new RenException("发布失败，网关确认版本不匹配，请同步网关状态");
        }
        markActive(price, reason);
        return price;
    }

    @Override
    public OfficialTtsPriceEntity syncPublished(Long id) {
        OfficialTtsPriceEntity price = priceDao.selectById(id);
        if (price == null) {
            throw new RenException("price_not_found");
        }
        String adminToken = sysParamsService.getValue("official.tts.admin.token", true);
        if (StringUtils.isBlank(adminToken)) {
            throw new RenException("admin_settle_token_required");
        }
        Map<String, Object> published = engine().gateway.publishedPrices(adminToken);
        Object rows = published.get("prices");
        if (!(rows instanceof List<?> list)) {
            throw new RenException("gateway_published_unavailable");
        }
        boolean found = false;
        for (Object row : list) {
            if (!(row instanceof Map<?, ?> m)) {
                continue;
            }
            if (price.getVersion().equals(String.valueOf(m.get("version")))
                    && price.getOperation().equals(String.valueOf(m.get("operation")))) {
                found = true;
                boolean enabled = Boolean.TRUE.equals(m.get("enabled")) || "true".equals(String.valueOf(m.get("enabled")));
                if (enabled) {
                    markActive(price, "sync_from_gateway");
                } else if (!OfficialTtsPriceLifecycle.ACTIVE.equals(price.getStatus())) {
                    price.setStatus(OfficialTtsPriceLifecycle.HISTORY);
                    priceDao.updateById(price);
                }
                break;
            }
        }
        if (!found && OfficialTtsPriceLifecycle.ACK_PENDING.equals(price.getStatus())) {
            price.setStatus(OfficialTtsPriceLifecycle.FAILED);
            priceDao.updateById(price);
        }
        return priceDao.selectById(id);
    }

    private void markActive(OfficialTtsPriceEntity price, String reason) {
        List<OfficialTtsPriceEntity> others = priceDao.selectList(new LambdaQueryWrapper<OfficialTtsPriceEntity>()
                .eq(OfficialTtsPriceEntity::getPriceKind, "sale_points")
                .eq(OfficialTtsPriceEntity::getOperation, price.getOperation())
                .eq(OfficialTtsPriceEntity::getUnit, price.getUnit())
                .eq(OfficialTtsPriceEntity::getStatus, OfficialTtsPriceLifecycle.ACTIVE)
                .ne(OfficialTtsPriceEntity::getId, price.getId()));
        for (OfficialTtsPriceEntity other : others) {
            other.setStatus(OfficialTtsPriceLifecycle.HISTORY);
            priceDao.updateById(other);
        }
        price.setStatus(OfficialTtsPriceLifecycle.ACTIVE);
        priceDao.updateById(price);
        OfficialTtsAuditEntity audit = new OfficialTtsAuditEntity();
        audit.setActorId(SecurityUser.getUserId());
        audit.setAction("publish_sale_price");
        audit.setObjectType("price");
        audit.setObjectId(String.valueOf(price.getId()));
        audit.setDetail("version=" + price.getVersion() + ";op=" + price.getOperation() + ";reason=" + reason);
        audit.setCreatedAt(new Date());
        auditDao.insert(audit);
    }

    private static String chargeModeOf(String operation) {
        if ("clone".equals(operation) || "design".equals(operation)) {
            return "per_request";
        }
        if ("query".equals(operation) || "delete".equals(operation)) {
            return "free";
        }
        return "metered";
    }

    @Override
    public void reconcile(Long jobId, String note) {
        throw new RenException("use_admin_note_or_settle");
    }

    @Override
    public void reconcile(Long jobId, Long finalTotal, String reason) {
        throw new RenException("use_admin_note_or_settle");
    }

    @Override
    public Map<String, Object> jobLedger(Long jobId) {
        OfficialTtsJobEntity job = jobDao.selectById(jobId);
        if (job == null || StringUtils.isBlank(job.getBillId())) {
            throw new RenException("任务或账单不存在");
        }
        Map<String, Object> data = new HashMap<>();
        data.put("jobId", job.getId());
        data.put("userId", job.getUserId());
        data.put("billId", job.getBillId());
        data.put("jobStatus", job.getStatus());
        data.put("salePriceVersion", job.getSalePriceVersion());
        data.put("javaSettledQuota", job.getSettledQuota());
        data.put("javaReservedQuota", job.getReservedQuota());
        data.put("finalTotalIsCumulative", true);
        data.put("saleUnitHint", OfficialTtsPriceLifecycle.UNIT_HINT_SALE);
        try {
            Map<String, Object> bill = engine().gateway.getBill(adminToken(), job.getBillId());
            data.put("gateway", bill);
            long charged = asLong(bill.get("charged"));
            long held = asLong(bill.get("held"));
            data.put("charged", charged);
            data.put("held", held);
            data.put("state", bill.get("state"));
            data.put("userQuota", bill.get("user_quota"));
            data.put("userUsedQuota", bill.get("user_used_quota"));
            data.put("tokenRemainQuota", bill.get("token_remain_quota"));
        } catch (RuntimeException e) {
            data.put("gatewayError", e.getMessage());
        }
        return data;
    }

    @Override
    public void addAdminNote(Long jobId, String operationId, String reason, String evidence) {
        try {
            OfficialTtsSettlePolicy.requireNote(operationId, reason);
        } catch (IllegalArgumentException e) {
            throw new RenException(e.getMessage());
        }
        if (auditDao.selectCount(new LambdaQueryWrapper<OfficialTtsAuditEntity>()
                .eq(OfficialTtsAuditEntity::getOperationId, operationId)) > 0) {
            return;
        }
        OfficialTtsJobEntity job = jobDao.selectById(jobId);
        if (job == null || StringUtils.isBlank(job.getBillId())) {
            throw new RenException("任务或账单不存在");
        }
        Map<String, Object> before = Map.of();
        try {
            before = engine().gateway.getBill(adminToken(), job.getBillId());
        } catch (RuntimeException ignored) {
        }
        try {
            Map<String, Object> body = new HashMap<>();
            body.put("reason", reason);
            body.put("evidence", StringUtils.defaultIfBlank(evidence, "console_note"));
            body.put("operation_id", operationId);
            engine().gateway.adminNote(adminToken(), job.getBillId(), body);
        } catch (RuntimeException e) {
            throw new RenException("备注失败: " + e.getMessage());
        }
        OfficialTtsAuditEntity audit = new OfficialTtsAuditEntity();
        audit.setUserId(job.getUserId());
        audit.setActorId(SecurityUser.getUserId());
        audit.setAction("admin_note");
        audit.setObjectType("job");
        audit.setObjectId(String.valueOf(jobId));
        audit.setOperationId(operationId);
        audit.setDetail("reason=" + reason + ";evidence=" + evidence + ";before=" + before
                + ";funds_changed=false");
        audit.setCreatedAt(new Date());
        auditDao.insert(audit);
        OfficialTtsLedgerEntity ledger = new OfficialTtsLedgerEntity();
        ledger.setJobId(jobId);
        ledger.setUserId(job.getUserId());
        ledger.setPhase("note");
        ledger.setQuota(0L);
        ledger.setNote(reason);
        ledgerDao.insert(ledger);
    }

    @Override
    public Map<String, Object> adminSettle(Long jobId, Long finalTotal, boolean finalTotalPresent, boolean confirmZero,
            boolean confirmed, String operationId, String reason, String evidence) {
        try {
            OfficialTtsSettlePolicy.requireSettle(finalTotal, finalTotalPresent, confirmZero, operationId, reason,
                    evidence);
        } catch (IllegalArgumentException e) {
            throw new RenException(e.getMessage());
        }
        if (!confirmed) {
            throw new RenException("settle_confirmation_required");
        }
        OfficialTtsAuditEntity existing = auditDao.selectOne(new LambdaQueryWrapper<OfficialTtsAuditEntity>()
                .eq(OfficialTtsAuditEntity::getOperationId, operationId).last("LIMIT 1"));
        if (existing != null) {
            OfficialTtsJobEntity job = jobDao.selectById(jobId);
            Map<String, Object> reused = jobLedger(jobId);
            reused.put("reused", true);
            reused.put("operationId", operationId);
            return reused;
        }
        OfficialTtsJobEntity job = jobDao.selectById(jobId);
        if (job == null || StringUtils.isBlank(job.getBillId())) {
            throw new RenException("任务或账单不存在");
        }
        Map<String, Object> bill = engine().gateway.getBill(adminToken(), job.getBillId());
        long charged = asLong(bill.get("charged"));
        long held = asLong(bill.get("held"));
        try {
            OfficialTtsSettlePolicy.assertNotBelowCharged(charged, finalTotal);
        } catch (IllegalStateException e) {
            throw new RenException(e.getMessage());
        }
        Map<String, Object> body = new HashMap<>();
        body.put("final_total", finalTotal);
        body.put("confirm_zero", confirmZero);
        body.put("review", false);
        body.put("reason", reason);
        body.put("evidence", evidence);
        body.put("operation_id", operationId);
        Map<String, Object> ack;
        try {
            ack = engine().gateway.adminResolve(adminToken(), job.getBillId(), body);
        } catch (RuntimeException e) {
            throw new RenException("结算失败: " + e.getMessage());
        }
        job.setSettledQuota(finalTotal);
        jobDao.updateById(job);
        OfficialTtsAuditEntity audit = new OfficialTtsAuditEntity();
        audit.setUserId(job.getUserId());
        audit.setActorId(SecurityUser.getUserId());
        audit.setAction("admin_settle");
        audit.setObjectType("job");
        audit.setObjectId(String.valueOf(jobId));
        audit.setOperationId(operationId);
        audit.setDetail("final_total=" + finalTotal + ";before_charged=" + charged + ";before_held=" + held
                + ";additional=" + OfficialTtsSettlePolicy.additionalCharge(charged, finalTotal)
                + ";release=" + OfficialTtsSettlePolicy.expectedRelease(charged, held, finalTotal)
                + ";reason=" + reason + ";evidence=" + evidence + ";ack=" + ack);
        audit.setCreatedAt(new Date());
        auditDao.insert(audit);
        OfficialTtsLedgerEntity ledger = new OfficialTtsLedgerEntity();
        ledger.setJobId(jobId);
        ledger.setUserId(job.getUserId());
        ledger.setPhase("admin_settle");
        ledger.setQuota(OfficialTtsSettlePolicy.additionalCharge(charged, finalTotal));
        ledger.setNote(reason);
        ledgerDao.insert(ledger);
        Map<String, Object> out = jobLedger(jobId);
        out.put("reused", Boolean.TRUE.equals(ack.get("reused")));
        out.put("operationId", operationId);
        out.put("finalTotalIsCumulative", true);
        out.put("additionalCharge", OfficialTtsSettlePolicy.additionalCharge(charged, finalTotal));
        return out;
    }

    private String adminToken() {
        String adminToken = sysParamsService.getValue("official.tts.admin.token", true);
        if (StringUtils.isBlank(adminToken)) {
            throw new RenException("admin_settle_token_required");
        }
        return adminToken;
    }

    private static long asLong(Object v) {
        if (v == null) {
            return 0L;
        }
        try {
            return Long.parseLong(String.valueOf(v).replace(".0", ""));
        } catch (NumberFormatException e) {
            return 0L;
        }
    }

    @Override
    public List<String> allowedVoiceCodes(Long userId) {
        List<String> owned = new java.util.ArrayList<>();
        if (userId != null) {
            List<OfficialTtsVoiceEntity> rows = voiceDao.selectList(new LambdaQueryWrapper<OfficialTtsVoiceEntity>()
                    .eq(OfficialTtsVoiceEntity::getUserId, userId)
                    .ne(OfficialTtsVoiceEntity::getStatus, "deleted")
                    .ne(OfficialTtsVoiceEntity::getStatus, "failed"));
            for (OfficialTtsVoiceEntity row : rows) {
                if (StringUtils.isNotBlank(row.getUpstreamVoiceId())) {
                    owned.add(row.getUpstreamVoiceId());
                }
            }
        }
        return OfficialTtsVoiceAcl.allowedCodes(owned);
    }

    @Override
    public byte[] serveInternalMedia(String token) {
        try {
            return engine().serveMedia(token);
        } catch (RuntimeException e) {
            throw new RenException(e.getMessage());
        }
    }

    private String requireToken(Long userId) {
        try {
            OneApiDeviceTokenVO vo = oneApiBindingService.resolveDeviceToken(userId);
            if (vo == null || StringUtils.isBlank(vo.getToken())) {
                throw new RenException("customer_token_required");
            }
            return vo.getToken();
        } catch (RenException e) {
            throw e;
        } catch (Exception e) {
            throw new RenException("customer_token_required");
        }
    }

    private OfficialTtsEngine engine() {
        String isolation = StringUtils.trimToEmpty(sysParamsService.getValue("official.tts.isolation", true));
        boolean isolated = "true".equalsIgnoreCase(isolation);
        String base = sysParamsService.getValue("official.tts.gateway.base", true);
        String mediaBase = sysParamsService.getValue("official.tts.media.base", true);
        String secret = sysParamsService.getValue("official.tts.media.secret", true);
        if (StringUtils.isBlank(secret)) {
            throw new IllegalStateException("media_secret_required");
        }
        if (!isolated) {
            if (StringUtils.isBlank(base) || StringUtils.isBlank(mediaBase)) {
                throw new IllegalStateException("official_tts_endpoints_required");
            }
            if (mediaBase.contains("localhost") || mediaBase.contains("127.0.0.1")) {
                throw new IllegalStateException("media_base_localhost_forbidden");
            }
            if (!mediaBase.startsWith("https://")) {
                throw new IllegalStateException("media_base_https_required");
            }
        } else {
            if (StringUtils.isBlank(base) || !(base.contains("127.0.0.1:13011") || base.contains("127.0.0.1:13012"))) {
                throw new IllegalStateException("isolation_gateway_required");
            }
            if (base.contains(":3011") && !base.contains(":13011") && !base.contains(":13012")) {
                throw new IllegalStateException("isolation_must_not_use_production_gateway");
            }
            mediaBase = StringUtils.defaultIfBlank(mediaBase, "http://127.0.0.1:18002/xiaozhi");
        }
        return new OfficialTtsEngine(new OfficialTtsGatewayClient(base), priceGate(), new DaoStore(), ROOT, secret,
                mediaBase);
    }

    private final class DaoStore implements OfficialTtsEngine.Store {
        @Override
        public OfficialTtsVoiceEntity findVoiceByIdem(long userId, String idem) {
            return voiceDao.selectOne(new LambdaQueryWrapper<OfficialTtsVoiceEntity>()
                    .eq(OfficialTtsVoiceEntity::getUserId, userId)
                    .eq(OfficialTtsVoiceEntity::getIdempotencyKey, idem));
        }

        @Override
        public void saveVoice(OfficialTtsVoiceEntity row) {
            if (row.getId() == null) {
                voiceDao.insert(row);
            } else {
                voiceDao.updateById(row);
            }
        }

        @Override
        public OfficialTtsJobEntity findJobByIdem(long userId, String idem) {
            return jobDao.selectOne(new LambdaQueryWrapper<OfficialTtsJobEntity>()
                    .eq(OfficialTtsJobEntity::getUserId, userId)
                    .eq(OfficialTtsJobEntity::getIdempotencyKey, idem));
        }

        @Override
        public void saveJob(OfficialTtsJobEntity row) {
            if (row.getId() == null) {
                jobDao.insert(row);
            } else {
                jobDao.updateById(row);
            }
        }

        @Override
        public void saveAsset(OfficialTtsAssetEntity row) {
            if (row.getId() == null) {
                assetDao.insert(row);
            } else {
                assetDao.updateById(row);
            }
        }

        @Override
        public OfficialTtsAssetEntity findAsset(long id) {
            return assetDao.selectById(id);
        }

        @Override
        public void saveLedger(OfficialTtsLedgerEntity row) {
            if (row.getQuota() != null && row.getQuota() <= 0 && "reserve".equals(row.getPhase())) {
                throw new RenException("quota_not_frozen");
            }
            ledgerDao.insert(row);
        }
    }

    private void requireEnhanced(Long userId) {
        if (!enhancedEnabledFor(userId)) {
            String status = resolveAccessStatus(userId, false, pricingReady());
            throw new RenException(accessStatusText(status));
        }
    }

    private boolean isVoiceBound(Long userId, OfficialTtsVoiceEntity row) {
        String code = row.getUpstreamVoiceId();
        if (StringUtils.isBlank(code) && StringUtils.isBlank(row.getAgentId())) {
            return false;
        }
        List<AgentEntity> agents = agentDao.selectList(
                new LambdaQueryWrapper<AgentEntity>().eq(AgentEntity::getUserId, userId));
        for (AgentEntity agent : agents) {
            if (StringUtils.isNotBlank(code) && code.equals(agent.getTtsVoiceId())) {
                return true;
            }
        }
        return false;
    }

    private AgentEntity requireAgent(Long userId, String agentId) {
        AgentEntity agent = agentService.selectById(agentId);
        if (agent == null || !userId.equals(agent.getUserId())) {
            throw new RenException("智能体不存在");
        }
        return agent;
    }

    private void rejectUnknown(Map<String, Object> body) {
        List<String> allowed = List.of("voice", "ttsVoiceId", "instruction", "languageHints", "dialect",
                "volume", "rate", "pitch", "hotFix", "style");
        for (String key : body.keySet()) {
            if (!allowed.contains(key)) {
                throw new RenException("未知参数: " + key);
            }
        }
    }

    private Map<String, Object> parseMap(String json) {
        if (StringUtils.isBlank(json)) {
            return new HashMap<>();
        }
        Map<String, Object> parsed = JsonUtils.parseObject(json, new TypeReference<Map<String, Object>>() {
        });
        return parsed == null ? new HashMap<>() : parsed;
    }

    private void ensureDisk() {
        try {
            Files.createDirectories(ROOT);
            long free = ROOT.toFile().getUsableSpace();
            if (free < MIN_FREE_BYTES) {
                throw new RenException("磁盘空间不足，拒绝上传");
            }
        } catch (IOException e) {
            throw new RenException("存储不可用");
        }
    }

    private Path saveUpload(Long userId, MultipartFile audio) {
        try {
            Files.createDirectories(ROOT);
            String name = userId + "-" + UUID.randomUUID() + "-" + StringUtils.defaultString(audio.getOriginalFilename(), "audio.wav");
            Path dest = ROOT.resolve(name.replaceAll("[^a-zA-Z0-9._-]", "_"));
            audio.transferTo(dest);
            return dest;
        } catch (IOException e) {
            throw new RenException("保存上传失败");
        }
    }

    private void audit(Long userId, Long actorId, String action, String objectType, String objectId, String detail) {
        OfficialTtsAuditEntity row = new OfficialTtsAuditEntity();
        row.setUserId(userId);
        row.setActorId(actorId);
        row.setAction(action);
        row.setObjectType(objectType);
        row.setObjectId(objectId);
        row.setDetail(detail);
        auditDao.insert(row);
    }
}
