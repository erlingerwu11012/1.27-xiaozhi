package xiaozhi.modules.wallpaperpack.util;

import java.util.Date;

/**
 * update_wallpaper 重连重投策略：次数上限 + 指数退避。
 */
public final class WallpaperRedeliveryPolicy {

    private WallpaperRedeliveryPolicy() {
    }

    public enum Action {
        DELIVER, SKIP_BACKOFF, STOP_MAX_ATTEMPTS
    }

    public static Action decide(int attemptCount, Date lastDeliveredAt,
            int maxAttempts, long backoffBaseMs, long nowMs) {
        if (attemptCount >= maxAttempts) {
            return Action.STOP_MAX_ATTEMPTS;
        }
        if (attemptCount <= 0 || lastDeliveredAt == null) {
            return Action.DELIVER;
        }
        long waitMs = backoffMsAfterAttempts(attemptCount, backoffBaseMs);
        long elapsed = nowMs - lastDeliveredAt.getTime();
        if (elapsed < waitMs) {
            return Action.SKIP_BACKOFF;
        }
        return Action.DELIVER;
    }

    public static long backoffMsAfterAttempts(int attemptCount, long backoffBaseMs) {
        if (attemptCount <= 0) {
            return 0;
        }
        long factor = 1L << Math.min(attemptCount - 1, 10);
        return backoffBaseMs * factor;
    }
}
