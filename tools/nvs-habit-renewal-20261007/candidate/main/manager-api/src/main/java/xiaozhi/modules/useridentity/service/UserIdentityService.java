package xiaozhi.modules.useridentity.service;

import java.util.List;
import java.util.Map;

import xiaozhi.modules.useridentity.vo.UserIdentityVO;

public interface UserIdentityService {
    UserIdentityVO create(Long accountId, String userId, String displayName);
    List<UserIdentityVO> list(Long accountId);
    UserIdentityVO updateDisplayName(Long accountId, String userId, String displayName);
    void bindFace(Long accountId, String userId, String faceProfileId);
    void unbindFace(Long accountId, String userId, String faceProfileId);
    void bindVoiceprint(Long accountId, String userId, String voiceprintId);
    void unbindVoiceprint(Long accountId, String userId, String voiceprintId);
    List<String> unboundVoiceprintIds(Long accountId, String agentId);
    List<String> boundFaceProfileIds(Long accountId);
    Map<String, Object> getActiveUser(Long accountId, String userId);
    List<Map<String, Object>> getFaceBindings(Long accountId);
    List<Map<String, Object>> getDeviceDirectory(Long accountId);
}
