package xiaozhi.modules.visualota.util;

import java.util.Set;

import xiaozhi.modules.rolepack.util.RolePackConstants;

/**
 * 跨 Spine / Wallpaper 视觉 OTA 调度常量。
 */
public final class VisualOtaConstants {

    private VisualOtaConstants() {
    }

    public static final String REDIS_DISPATCH_PREFIX = "visualota:dispatch:";

    /**
     * 设备视觉 OTA 调度租约 TTL（秒）。进程异常退出后自动过期，避免永久占槽。
     */
    public static final long DISPATCH_LEASE_TTL_SECONDS = 3600L;

    /**
     * 占用视觉 OTA 槽位、阻塞异类资源下发的状态（已推送至设备，等待 ACK 或进行中）。
     * queued / retrying 不占槽，允许异类任务在 DB 中并存。
     */
    public static final Set<String> DISPATCH_HOLDING_STATES = Set.of(
            RolePackConstants.STATE_SENT,
            RolePackConstants.STATE_ACCEPTED,
            RolePackConstants.STATE_IN_PROGRESS,
            RolePackConstants.STATE_DOWNLOADING,
            RolePackConstants.STATE_VERIFYING,
            RolePackConstants.STATE_APPLYING);
}
