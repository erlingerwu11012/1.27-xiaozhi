package xiaozhi.modules.rolepack.util;

import java.util.Date;

/**
 * update_spine 重连重投策略：次数上限 + 指数退避，避免设备异常重启后立即无限重投。
 */
public final class SpineRedeliveryPolicy {

    private SpineRedeliveryPolicy() {
    }

    public enum Action {
        /** 允许本次投递 */
        DELIVER,
        /** 仍在退避窗口内，跳过本次（任务保持可投递状态） */
        SKIP_BACKOFF,
        /** 已达最大投递次数，应停止自动投递 */
        STOP_MAX_ATTEMPTS
    }

    /**
     * @param attemptCount 已成功发出的投递次数（含首次 deploy 推送）
     * @param lastSentAt   最近一次实际投递时间
     * @param maxAttempts  最大投递次数（建议 3）
     * @param baseBackoffMs 指数退避基准毫秒（第 1 次投递后的等待 = base）
     * @param nowMs        当前时间
     */
    public static Action decide(Integer attemptCount, Date lastSentAt, int maxAttempts,
            long baseBackoffMs, long nowMs) {
        int attempts = attemptCount == null ? 0 : Math.max(0, attemptCount);
        int max = Math.max(1, maxAttempts);
        if (attempts >= max) {
            return Action.STOP_MAX_ATTEMPTS;
        }
        if (lastSentAt != null && attempts > 0) {
            long waitMs = backoffMsAfterAttempts(attempts, baseBackoffMs);
            if (nowMs - lastSentAt.getTime() < waitMs) {
                return Action.SKIP_BACKOFF;
            }
        }
        return Action.DELIVER;
    }

    /**
     * 已投递 {@code attempts} 次后，下次允许投递前的最短等待。
     * attempts=1 → base；attempts=2 → 2*base；attempts=3 → 4*base …
     */
    public static long backoffMsAfterAttempts(int attempts, long baseBackoffMs) {
        long base = Math.max(0L, baseBackoffMs);
        int exp = Math.max(0, Math.min(attempts - 1, 10));
        return base * (1L << exp);
    }
}
