package xiaozhi.modules.wallpaperpack.service;

public interface WallpaperPackAuditService {
    void log(String action, Long actorUserId, String deviceId, String packId, String taskId,
            String detail, String errorCode);
}
