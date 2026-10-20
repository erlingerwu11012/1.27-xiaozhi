package xiaozhi.modules.rolepack.util;

import java.util.Map;
import java.util.Set;

/**
 * 角色部署任务状态机（中央权威真相源）。
 * 不允许回退已完成任务；终态不得再推进。
 *
 * queued -> sent -> accepted -> in_progress -> completed
 *                          ├-> failed
 *                          ├-> cancelled
 *                          └-> needs_manual_review
 */
public final class RoleDeployStateMachine {

    private RoleDeployStateMachine() {
    }

    private static final Set<String> STOP_STATES = Set.of(
            RolePackConstants.STATE_FAILED,
            RolePackConstants.STATE_EXPIRED,
            RolePackConstants.STATE_CANCELLED,
            RolePackConstants.STATE_NEEDS_MANUAL_REVIEW);

    private static final Map<String, Set<String>> ALLOWED = Map.ofEntries(
            Map.entry(RolePackConstants.STATE_QUEUED, union(Set.of(
                    RolePackConstants.STATE_SENT,
                    RolePackConstants.STATE_ACCEPTED,
                    RolePackConstants.STATE_IN_PROGRESS,
                    RolePackConstants.STATE_RETRYING), STOP_STATES)),
            Map.entry(RolePackConstants.STATE_RETRYING, union(Set.of(
                    RolePackConstants.STATE_QUEUED,
                    RolePackConstants.STATE_SENT,
                    RolePackConstants.STATE_ACCEPTED,
                    RolePackConstants.STATE_IN_PROGRESS), STOP_STATES)),
            Map.entry(RolePackConstants.STATE_SENT, union(Set.of(
                    RolePackConstants.STATE_ACCEPTED,
                    RolePackConstants.STATE_IN_PROGRESS,
                    RolePackConstants.STATE_QUEUED,
                    RolePackConstants.STATE_RETRYING), STOP_STATES)),
            Map.entry(RolePackConstants.STATE_ACCEPTED, union(Set.of(
                    RolePackConstants.STATE_IN_PROGRESS,
                    RolePackConstants.STATE_SENT,
                    RolePackConstants.STATE_QUEUED,
                    RolePackConstants.STATE_RETRYING), STOP_STATES)),
            Map.entry(RolePackConstants.STATE_IN_PROGRESS, union(Set.of(
                    RolePackConstants.STATE_COMPLETED), STOP_STATES)),
            // 历史兼容状态：视作 in_progress 的等价态
            Map.entry(RolePackConstants.STATE_DOWNLOADING, union(Set.of(
                    RolePackConstants.STATE_COMPLETED,
                    RolePackConstants.STATE_IN_PROGRESS,
                    RolePackConstants.STATE_VERIFYING,
                    RolePackConstants.STATE_APPLYING), STOP_STATES)),
            Map.entry(RolePackConstants.STATE_VERIFYING, union(Set.of(
                    RolePackConstants.STATE_COMPLETED,
                    RolePackConstants.STATE_IN_PROGRESS,
                    RolePackConstants.STATE_APPLYING), STOP_STATES)),
            Map.entry(RolePackConstants.STATE_APPLYING, union(Set.of(
                    RolePackConstants.STATE_COMPLETED,
                    RolePackConstants.STATE_SUCCEEDED), STOP_STATES)));

    private static Set<String> union(Set<String> a, Set<String> b) {
        java.util.HashSet<String> out = new java.util.HashSet<>(a);
        out.addAll(b);
        return Set.copyOf(out);
    }

    /**
     * 设备上报 phase -> 中央状态。
     * accepted/waiting -> accepted；downloading/verifying/applying -> in_progress；
     * success -> completed；failed -> failed。
     */
    public static String phaseToState(String phase) {
        if (phase == null) {
            return null;
        }
        return switch (phase) {
            case "waiting", "accepted" -> RolePackConstants.STATE_ACCEPTED;
            case "downloading", "verifying", "applying" -> RolePackConstants.STATE_IN_PROGRESS;
            case "success" -> RolePackConstants.STATE_COMPLETED;
            case "failed" -> RolePackConstants.STATE_FAILED;
            default -> null;
        };
    }

    public static boolean canTransition(String from, String to) {
        if (from == null || to == null) {
            return false;
        }
        if (from.equals(to)) {
            return true;
        }
        if (RolePackConstants.TERMINAL_STATES.contains(from)) {
            return false;
        }
        Set<String> next = ALLOWED.get(from);
        return next != null && next.contains(to);
    }

    /** 成功 ACK 是否允许（幂等：已 completed/succeeded 仍返回 true）。 */
    public static boolean canComplete(String from) {
        return from != null && RolePackConstants.COMPLETABLE_STATES.contains(from);
    }

    public static boolean isRetryableError(String errorCode) {
        if (errorCode == null) {
            return false;
        }
        return "E_BUSY".equals(errorCode) || "E_NETWORK".equals(errorCode);
    }

    public static boolean isNonRetryableError(String errorCode) {
        if (errorCode == null) {
            return false;
        }
        // E_NVS：设备 NVS 异常，需人工恢复；终态 failed，不自动重投
        return Set.of("E_SIG", "E_SHA", "E_SIZE", "E_BUNDLE", "E_MIN_FW", "E_BOARD", "E_NVS")
                .contains(errorCode);
    }
}
