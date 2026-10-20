package xiaozhi.modules.rolepack.service;

public interface RolePackAuditService {
    void log(String action, Long actorUserId, String deviceId, String packId, String taskId,
            String detail, String errorCode);
}
