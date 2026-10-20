package xiaozhi.modules.rolepack.service.impl;

import java.util.Date;

import org.springframework.stereotype.Service;

import lombok.RequiredArgsConstructor;
import xiaozhi.modules.rolepack.dao.RolePackAuditDao;
import xiaozhi.modules.rolepack.entity.RolePackAuditEntity;
import xiaozhi.modules.rolepack.service.RolePackAuditService;

@Service
@RequiredArgsConstructor
public class RolePackAuditServiceImpl implements RolePackAuditService {

    private final RolePackAuditDao auditDao;

    @Override
    public void log(String action, Long actorUserId, String deviceId, String packId, String taskId,
            String detail, String errorCode) {
        RolePackAuditEntity e = new RolePackAuditEntity();
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
