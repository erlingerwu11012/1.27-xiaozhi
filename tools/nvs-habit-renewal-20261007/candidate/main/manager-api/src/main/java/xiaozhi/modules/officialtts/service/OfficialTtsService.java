package xiaozhi.modules.officialtts.service;

import java.util.List;
import java.util.Map;

import org.springframework.web.multipart.MultipartFile;

import xiaozhi.modules.officialtts.entity.OfficialTtsJobEntity;
import xiaozhi.modules.officialtts.entity.OfficialTtsPriceEntity;
import xiaozhi.modules.officialtts.entity.OfficialTtsVoiceEntity;

public interface OfficialTtsService {
    Map<String, Object> capabilities(Long userId);

    /** Whether official TTS enhanced entry is open for this user (mode + kill-switch + allowlist). */
    boolean enhancedEnabledFor(Long userId);

    String enhancedMode();

    OfficialTtsVoiceEntity createVoice(Long userId, String idempotencyKey, Map<String, Object> body, MultipartFile audio);

    List<OfficialTtsVoiceEntity> listVoices(Long userId);

    OfficialTtsVoiceEntity getVoice(Long userId, Long id);

    OfficialTtsVoiceEntity renameVoice(Long userId, Long id, String name);

    void deleteVoice(Long userId, Long id);

    OfficialTtsJobEntity createJob(Long userId, String idempotencyKey, Map<String, Object> body);

    OfficialTtsJobEntity getJob(Long userId, Long id);

    List<OfficialTtsJobEntity> listJobs(Long userId);

    void cancelJob(Long userId, Long id);

    void deleteJob(Long userId, Long id);

    byte[] downloadJob(Long userId, Long id);

    byte[] downloadVoicePreview(Long userId, Long id);

    /** 确保音色有试听音频（缺失时按需生成），并返回音频字节。 */
    byte[] ensureVoicePreview(Long userId, Long id);

    OfficialTtsVoiceEntity bindVoice(Long userId, Long voiceId, String agentId);

    Map<String, Object> adminOverview();

    OfficialTtsPriceEntity updatePrice(OfficialTtsPriceEntity price);

    OfficialTtsPriceEntity draftFromPublished(Long id);

    OfficialTtsPriceEntity publishPrice(Long id, String reason);

    OfficialTtsPriceEntity syncPublished(Long id);

    Map<String, Object> jobLedger(Long jobId);

    void addAdminNote(Long jobId, String operationId, String reason, String evidence);

    Map<String, Object> adminSettle(Long jobId, Long finalTotal, boolean finalTotalPresent, boolean confirmZero,
            boolean confirmed, String operationId, String reason, String evidence);

    void reconcile(Long jobId, String note);

    void reconcile(Long jobId, Long finalTotal, String reason);

    int syncDeviceTokenModels();

    byte[] serveInternalMedia(String token);

    java.util.List<String> allowedVoiceCodes(Long userId);
}
