package xiaozhi.modules.wallpaperpack.util;

import java.util.Set;

public final class WallpaperPackConstants {

    private WallpaperPackConstants() {
    }

    /** 壁纸包最大大小：2 MiB */
    public static final long MAX_PACK_SIZE = 2L * 1024 * 1024;

    public static final int MAX_WALLPAPER_ITEMS = 16;

    public static final String STATUS_DRAFT = "draft";
    public static final String STATUS_PUBLISHED = "published";
    public static final String STATUS_DISABLED = "disabled";

    public static final String STATE_QUEUED = "queued";
    public static final String STATE_SENT = "sent";
    public static final String STATE_ACCEPTED = "accepted";
    public static final String STATE_IN_PROGRESS = "in_progress";
    public static final String STATE_COMPLETED = "completed";
    public static final String STATE_FAILED = "failed";
    public static final String STATE_EXPIRED = "expired";
    public static final String STATE_CANCELLED = "cancelled";
    public static final String STATE_NEEDS_MANUAL_REVIEW = "needs_manual_review";
    public static final String STATE_RETRYING = "retrying";
    public static final String STATE_DOWNLOADING = "downloading";
    public static final String STATE_VERIFYING = "verifying";
    public static final String STATE_APPLYING = "applying";
    public static final String STATE_SUCCEEDED = "succeeded";

    public static final Set<String> ACTIVE_STATES = Set.of(
            STATE_QUEUED, STATE_RETRYING, STATE_SENT, STATE_ACCEPTED, STATE_IN_PROGRESS,
            STATE_DOWNLOADING, STATE_VERIFYING, STATE_APPLYING);

    public static final Set<String> REDELIVERABLE_STATES = Set.of(
            STATE_QUEUED, STATE_RETRYING, STATE_SENT, STATE_ACCEPTED, STATE_IN_PROGRESS,
            STATE_DOWNLOADING, STATE_VERIFYING, STATE_APPLYING);

    public static final Set<String> CANCELABLE_UPDATE_WALLPAPER_STATES = Set.of(
            STATE_QUEUED, STATE_RETRYING, STATE_SENT, STATE_ACCEPTED, STATE_IN_PROGRESS,
            STATE_DOWNLOADING, STATE_VERIFYING, STATE_APPLYING);

    public static final Set<String> TERMINAL_STATES = Set.of(
            STATE_COMPLETED, STATE_SUCCEEDED, STATE_FAILED, STATE_EXPIRED,
            STATE_CANCELLED, STATE_NEEDS_MANUAL_REVIEW);

    public static final Set<String> SUCCESS_STATES = Set.of(
            STATE_COMPLETED, STATE_SUCCEEDED);

    public static final Set<String> COMPLETABLE_STATES = Set.of(
            STATE_SENT, STATE_ACCEPTED, STATE_IN_PROGRESS,
            STATE_DOWNLOADING, STATE_VERIFYING, STATE_APPLYING,
            STATE_COMPLETED, STATE_SUCCEEDED);

    public static final Set<String> COMPLETABLE_ACTIVE_STATES = Set.of(
            STATE_SENT, STATE_ACCEPTED, STATE_IN_PROGRESS,
            STATE_DOWNLOADING, STATE_VERIFYING, STATE_APPLYING);

    public static final String ERR_MAX_REDELIVER = "E_MAX_REDELIVER";
    public static final String ERR_ABNORMAL_DISCONNECT = "E_ABNORMAL_DISCONNECT";
    public static final String ERR_MANUAL_CANCEL = "E_MANUAL_CANCEL";

    public static final String SIG_ALG_ES256 = "ES256";

    public static final String BUNDLE_WALLPAPER_JSON = "wallpaper.json";

    public static final Set<String> ALLOWED_IMAGE_EXTENSIONS = Set.of(".png", ".jpg", ".jpeg");

    /** Redis 前缀与 role-pack 隔离 */
    public static final String REDIS_DOWNLOAD_PREFIX = "wallpaperpack:download:";
    public static final String REDIS_DOWNLOAD_COUNT_PREFIX = "wallpaperpack:download:count:";
    public static final String REDIS_RESOURCE_TYPE = "wallpaper";

    public static final Set<String> IN_FLIGHT_STATES = Set.of(
            STATE_IN_PROGRESS, STATE_DOWNLOADING, STATE_VERIFYING, STATE_APPLYING);

    public static final String CMD_UPDATE_WALLPAPER = "update_wallpaper";
    public static final String MSG_TYPE_SYSTEM = "system";
    public static final String MSG_TYPE_WALLPAPER_OTA_ACK = "wallpaper_ota_ack";

    public static final String PENDING_CLAIM_ATTEMPT_KEY = "__claim_attempt";
    public static final String PENDING_CLAIM_LEASE_KEY = "__claim_lease_id";
    public static final String PENDING_CLAIM_VERSION_KEY = "__claim_version";
    public static final String PENDING_CLAIM_SESSION_KEY = "__claim_session_id";
}
