package xiaozhi.modules.officialtts.controller;

import java.util.List;
import java.util.Map;

import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.officialtts.entity.OfficialTtsJobEntity;
import xiaozhi.modules.officialtts.entity.OfficialTtsVoiceEntity;
import xiaozhi.modules.officialtts.service.OfficialTtsService;
import xiaozhi.modules.security.user.SecurityUser;

@RestController
@RequestMapping
@RequiredArgsConstructor
@Tag(name = "官方TTS")
public class OfficialTtsController {
    private final OfficialTtsService officialTtsService;

    @GetMapping("/official-tts/capabilities")
    @RequiresPermissions("sys:role:normal")
    @Operation(summary = "当前客户可用的官方TTS能力")
    public Result<Map<String, Object>> capabilities() {
        return new Result<Map<String, Object>>().ok(officialTtsService.capabilities(SecurityUser.getUserId()));
    }

    @PostMapping(value = "/official-tts/assets", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @RequiresPermissions("sys:role:normal")
    public Result<OfficialTtsVoiceEntity> upload(
            @RequestHeader(value = "Idempotency-Key", required = false) String idem,
            @RequestParam Map<String, Object> body,
            @RequestPart(value = "file", required = false) MultipartFile file) {
        return new Result<OfficialTtsVoiceEntity>().ok(
                officialTtsService.createVoice(SecurityUser.getUserId(), idem, body, file));
    }

    @GetMapping("/official-tts/voices")
    @RequiresPermissions("sys:role:normal")
    public Result<List<OfficialTtsVoiceEntity>> voices() {
        return new Result<List<OfficialTtsVoiceEntity>>().ok(officialTtsService.listVoices(SecurityUser.getUserId()));
    }

    @PostMapping("/official-tts/voices")
    @RequiresPermissions("sys:role:normal")
    public Result<OfficialTtsVoiceEntity> createVoice(
            @RequestHeader(value = "Idempotency-Key", required = false) String idem,
            @RequestBody Map<String, Object> body) {
        return new Result<OfficialTtsVoiceEntity>().ok(
                officialTtsService.createVoice(SecurityUser.getUserId(), idem, body, null));
    }

    @GetMapping("/official-tts/voices/{id}")
    @RequiresPermissions("sys:role:normal")
    public Result<OfficialTtsVoiceEntity> voice(@PathVariable Long id) {
        return new Result<OfficialTtsVoiceEntity>().ok(officialTtsService.getVoice(SecurityUser.getUserId(), id));
    }

    @PutMapping("/official-tts/voices/{id}")
    @RequiresPermissions("sys:role:normal")
    @Operation(summary = "重命名音色资产")
    public Result<OfficialTtsVoiceEntity> renameVoice(
            @PathVariable Long id,
            @RequestBody Map<String, Object> body) {
        String name = body == null ? null : String.valueOf(body.getOrDefault("name", ""));
        return new Result<OfficialTtsVoiceEntity>().ok(
                officialTtsService.renameVoice(SecurityUser.getUserId(), id, name));
    }

    @PostMapping("/official-tts/voices/{id}/bind")
    @RequiresPermissions("sys:role:normal")
    public Result<OfficialTtsVoiceEntity> bind(
            @PathVariable Long id,
            @RequestParam("agentId") String agentId) {
        return new Result<OfficialTtsVoiceEntity>().ok(
                officialTtsService.bindVoice(SecurityUser.getUserId(), id, agentId));
    }

    @DeleteMapping("/official-tts/voices/{id}")
    @RequiresPermissions("sys:role:normal")
    public Result<Void> deleteVoice(@PathVariable Long id) {
        officialTtsService.deleteVoice(SecurityUser.getUserId(), id);
        return new Result<>();
    }

    @GetMapping("/official-tts/voices/{id}/preview")
    @RequiresPermissions("sys:role:normal")
    @Operation(summary = "试听/下载音色设计预览音频")
    public ResponseEntity<byte[]> voicePreview(@PathVariable Long id) {
        byte[] data = officialTtsService.downloadVoicePreview(SecurityUser.getUserId(), id);
        return previewResponse(id, data);
    }

    @PostMapping("/official-tts/voices/{id}/preview")
    @RequiresPermissions("sys:role:normal")
    @Operation(summary = "生成（如缺失）并试听音色预览音频")
    public ResponseEntity<byte[]> generateVoicePreview(@PathVariable Long id) {
        byte[] data = officialTtsService.ensureVoicePreview(SecurityUser.getUserId(), id);
        return previewResponse(id, data);
    }

    private ResponseEntity<byte[]> previewResponse(Long id, byte[] data) {
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "inline; filename=voice-preview-" + id + ".wav")
                .contentType(MediaType.parseMediaType("audio/wav"))
                .body(data);
    }

    @PostMapping("/official-tts/jobs")
    @RequiresPermissions("sys:role:normal")
    public Result<OfficialTtsJobEntity> createJob(
            @RequestHeader(value = "Idempotency-Key", required = false) String idem,
            @RequestBody Map<String, Object> body) {
        return new Result<OfficialTtsJobEntity>().ok(officialTtsService.createJob(SecurityUser.getUserId(), idem, body));
    }

    @GetMapping("/official-tts/jobs")
    @RequiresPermissions("sys:role:normal")
    public Result<List<OfficialTtsJobEntity>> jobs() {
        return new Result<List<OfficialTtsJobEntity>>().ok(officialTtsService.listJobs(SecurityUser.getUserId()));
    }

    @GetMapping("/official-tts/jobs/{id}")
    @RequiresPermissions("sys:role:normal")
    public Result<OfficialTtsJobEntity> job(@PathVariable Long id) {
        return new Result<OfficialTtsJobEntity>().ok(officialTtsService.getJob(SecurityUser.getUserId(), id));
    }

    @PostMapping("/official-tts/jobs/{id}/cancel")
    @RequiresPermissions("sys:role:normal")
    public Result<Void> cancel(@PathVariable Long id) {
        officialTtsService.cancelJob(SecurityUser.getUserId(), id);
        return new Result<>();
    }

    @DeleteMapping("/official-tts/jobs/{id}")
    @RequiresPermissions("sys:role:normal")
    public Result<Void> deleteJob(@PathVariable Long id) {
        officialTtsService.deleteJob(SecurityUser.getUserId(), id);
        return new Result<>();
    }

    @GetMapping("/official-tts/jobs/{id}/download")
    @RequiresPermissions("sys:role:normal")
    public ResponseEntity<byte[]> download(@PathVariable Long id) {
        OfficialTtsJobEntity job = officialTtsService.getJob(SecurityUser.getUserId(), id);
        byte[] data = officialTtsService.downloadJob(SecurityUser.getUserId(), id);
        String format = extractFormat(job);
        String filename = "official-tts-" + id + "." + format;
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "inline; filename=" + filename)
                .contentType(MediaType.parseMediaType(audioMediaType(format)))
                .body(data);
    }

    private static String extractFormat(OfficialTtsJobEntity job) {
        if (job == null || job.getRequestJson() == null) {
            return "wav";
        }
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> req = xiaozhi.common.utils.JsonUtils.parseObject(job.getRequestJson(), Map.class);
            if (req != null && req.get("format") != null) {
                return String.valueOf(req.get("format")).toLowerCase();
            }
        } catch (Exception ignored) {
            // fall through
        }
        return "wav";
    }

    private static String audioMediaType(String format) {
        if ("mp3".equals(format)) {
            return "audio/mpeg";
        }
        if ("opus".equals(format)) {
            return "audio/ogg";
        }
        if ("pcm".equals(format)) {
            return "application/octet-stream";
        }
        return "audio/wav";
    }

    @GetMapping("/official-tts/internal/media/{token}")
    @Operation(summary = "网关拉取复刻素材（HMAC 短时令牌）")
    public ResponseEntity<byte[]> internalMedia(@PathVariable("token") String token) {
        byte[] data = officialTtsService.serveInternalMedia(token);
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType("audio/wav"))
                .body(data);
    }
}
