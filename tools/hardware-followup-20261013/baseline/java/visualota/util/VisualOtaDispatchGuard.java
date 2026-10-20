package xiaozhi.modules.visualota.util;

import java.util.UUID;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Component;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.redis.RedisUtils;
import xiaozhi.modules.rolepack.dao.RoleDeployTaskDao;
import xiaozhi.modules.rolepack.entity.RoleDeployTaskEntity;
import xiaozhi.modules.wallpaperpack.dao.WallpaperDeployTaskDao;
import xiaozhi.modules.wallpaperpack.entity.WallpaperDeployTaskEntity;

/**
 * 同设备 Spine / Wallpaper 视觉 OTA 跨资源串行调度守卫。
 * <p>
 * 同一 device_id 允许两类任务分别存在（queued/retrying），但同一时刻仅允许一个任务
 * 处于推送/下载/等待 ACK 阶段。通过 Redis 租约（SET NX + TTL）协调跨服务并发，
 * 并结合双表 DISPATCH_HOLDING_STATES 查询作为持久化真相补充。
 * <p>
 * 租约生命周期：
 * <ul>
 *   <li>创建：deploy 首次推送或 pending 重投在 push 前 {@link #tryClaim}</li>
 *   <li>释放：success/failed(E_BUSY 重试)/cancel/release/abnormal/终态 {@link #release}</li>
 *   <li>过期：{@link VisualOtaConstants#DISPATCH_LEASE_TTL_SECONDS} 无刷新则自动释放（进程崩溃恢复）</li>
 * </ul>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class VisualOtaDispatchGuard {

    public enum ClaimResult {
        /** 新领取成功 */
        CLAIMED,
        /** 同一 task 已持有（幂等/重入） */
        ALREADY_HELD_BY_SELF,
        /** 另一视觉 OTA 资源占用槽位 */
        BLOCKED_BY_OTHER_RESOURCE,
        /** 参数无效 */
        INVALID
    }

    private record DispatchLease(String resourceType, String taskId, String leaseId, long acquiredAtMs) {
    }

    private final RedisUtils redisUtils;
    private final RoleDeployTaskDao spineTaskDao;
    private final WallpaperDeployTaskDao wallpaperTaskDao;
    private final ObjectMapper objectMapper = new ObjectMapper();

    /**
     * 在将任务推进至 sent / 向设备推送前调用。
     */
    public ClaimResult tryClaim(String deviceId, VisualOtaResourceType resourceType, String taskId) {
        if (StringUtils.isBlank(deviceId) || StringUtils.isBlank(taskId) || resourceType == null) {
            return ClaimResult.INVALID;
        }
        if (hasOtherResourceHolding(deviceId, resourceType)) {
            log.info(
                    "[visual_ota] claim_blocked device_id={} resource={} task_id={} reason=other_resource_in_flight",
                    deviceId, resourceType.value(), taskId);
            return ClaimResult.BLOCKED_BY_OTHER_RESOURCE;
        }

        String key = redisKey(deviceId);
        DispatchLease existing = readLease(key);
        if (existing != null) {
            if (matches(existing, resourceType, taskId)) {
                refreshLeaseTtl(key);
                return ClaimResult.ALREADY_HELD_BY_SELF;
            }
            log.info(
                    "[visual_ota] claim_blocked device_id={} resource={} task_id={} holder={}/{} reason=redis_lease",
                    deviceId, resourceType.value(), taskId, existing.resourceType(), existing.taskId());
            return ClaimResult.BLOCKED_BY_OTHER_RESOURCE;
        }

        DispatchLease lease = new DispatchLease(
                resourceType.value(),
                taskId,
                UUID.randomUUID().toString(),
                System.currentTimeMillis());
        boolean ok = redisUtils.setIfAbsent(key, serialize(lease), VisualOtaConstants.DISPATCH_LEASE_TTL_SECONDS);
        if (!ok) {
            existing = readLease(key);
            if (existing != null && matches(existing, resourceType, taskId)) {
                return ClaimResult.ALREADY_HELD_BY_SELF;
            }
            return ClaimResult.BLOCKED_BY_OTHER_RESOURCE;
        }
        log.info(
                "[visual_ota] claim_ok device_id={} resource={} task_id={} lease_id={}",
                deviceId, resourceType.value(), taskId, lease.leaseId());
        return ClaimResult.CLAIMED;
    }

    /**
     * 任务完成、可重投（E_BUSY）、取消、release-pending、异常断开时释放槽位。
     */
    public void release(String deviceId, VisualOtaResourceType resourceType, String taskId) {
        if (StringUtils.isBlank(deviceId) || StringUtils.isBlank(taskId) || resourceType == null) {
            return;
        }
        String key = redisKey(deviceId);
        DispatchLease existing = readLease(key);
        if (existing == null) {
            return;
        }
        if (!matches(existing, resourceType, taskId)) {
            return;
        }
        redisUtils.delete(key);
        log.info(
                "[visual_ota] release device_id={} resource={} task_id={} lease_id={}",
                deviceId, resourceType.value(), taskId, existing.leaseId());
    }

    private boolean hasOtherResourceHolding(String deviceId, VisualOtaResourceType self) {
        if (self == VisualOtaResourceType.SPINE) {
            WallpaperDeployTaskEntity other = wallpaperTaskDao.selectOne(
                    new LambdaQueryWrapper<WallpaperDeployTaskEntity>()
                            .eq(WallpaperDeployTaskEntity::getDeviceId, deviceId)
                            .in(WallpaperDeployTaskEntity::getState, VisualOtaConstants.DISPATCH_HOLDING_STATES)
                            .orderByDesc(WallpaperDeployTaskEntity::getCreatedAt)
                            .last("LIMIT 1"));
            return other != null;
        }
        RoleDeployTaskEntity other = spineTaskDao.selectOne(
                new LambdaQueryWrapper<RoleDeployTaskEntity>()
                        .eq(RoleDeployTaskEntity::getDeviceId, deviceId)
                        .in(RoleDeployTaskEntity::getState, VisualOtaConstants.DISPATCH_HOLDING_STATES)
                        .orderByDesc(RoleDeployTaskEntity::getCreatedAt)
                        .last("LIMIT 1"));
        return other != null;
    }

    private static boolean matches(DispatchLease lease, VisualOtaResourceType resourceType, String taskId) {
        return resourceType.value().equals(lease.resourceType()) && taskId.equals(lease.taskId());
    }

    private static String redisKey(String deviceId) {
        return VisualOtaConstants.REDIS_DISPATCH_PREFIX + deviceId;
    }

    private DispatchLease readLease(String key) {
        Object raw = redisUtils.get(key);
        if (raw == null) {
            return null;
        }
        try {
            return objectMapper.readValue(raw.toString(), DispatchLease.class);
        } catch (Exception e) {
            log.warn("[visual_ota] lease_parse_failed key={} reason={}", key, e.getMessage());
            return null;
        }
    }

    private String serialize(DispatchLease lease) {
        try {
            return objectMapper.writeValueAsString(lease);
        } catch (Exception e) {
            throw new IllegalStateException("序列化视觉 OTA 租约失败", e);
        }
    }

    private void refreshLeaseTtl(String key) {
        redisUtils.expire(key, VisualOtaConstants.DISPATCH_LEASE_TTL_SECONDS);
    }
}
