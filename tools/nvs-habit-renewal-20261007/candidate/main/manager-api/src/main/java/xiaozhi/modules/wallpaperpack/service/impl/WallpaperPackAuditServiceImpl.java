package xiaozhi.modules.wallpaperpack.service.impl;

import java.util.Date;

import org.springframework.stereotype.Service;

import lombok.RequiredArgsConstructor;
import xiaozhi.modules.wallpaperpack.dao.WallpaperPackAuditDao;
import xiaozhi.modules.wallpaperpack.entity.WallpaperPackAuditEntity;
import xiaozhi.modules.wallpaperpack.service.WallpaperPackAuditService;

@Service
@RequiredArgsConstructor
public class WallpaperPackAuditServiceImpl implements WallpaperPackAuditService {

    private final WallpaperPackAuditDao auditDao;

    @Override
    public void log(String action, Long actorUserId, String deviceId, String packId, String taskId,
            String detail, String errorCode) {
        WallpaperPackAuditEntity e = new WallpaperPackAuditEntity();
        e.setAction(action);
        e.setActorUserId(actorUserId);
        e.setDeviceId(deviceId);
        e.setPackId(packId);
        e.setTaskId(taskId);
        if (detail != null && detail.length() > 1000) {
            detail = detail.substring(0, 1000);
        }
        e.setDetail(detail);
        e.setErrorCode(errorCode);
        e.setCreatedAt(new Date());
        auditDao.insert(e);
    }
}
