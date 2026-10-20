package xiaozhi.modules.rolepack.util;

import java.util.Set;

public final class RolePackConstants {

    private RolePackConstants() {
    }

    /** 角色包最大大小：4 MiB */
    public static final long MAX_PACK_SIZE = 4L * 1024 * 1024;

    public static final String STATUS_DRAFT = "draft";
    public static final String STATUS_PUBLISHED = "published";
    public static final String STATUS_DISABLED = "disabled";

    // ---- 中央任务状态机（权威真相源，落库 ai_role_deploy_task.state）----
    // queued -> sent -> accepted -> in_progress -> completed
    //                          ├-> failed / cancelled / needs_manual_review / expired
    public static final String STATE_QUEUED = "queued";
    public static final String STATE_SENT = "sent";
    public static final String STATE_ACCEPTED = "accepted";
    public static final String STATE_IN_PROGRESS = "in_progress";
    public static final String STATE_COMPLETED = "completed";

    public static final String STATE_FAILED = "failed";
    public static final String STATE_EXPIRED = "expired";
    public static final String STATE_CANCELLED = "cancelled";
    public static final String STATE_NEEDS_MANUAL_REVIEW = "needs_manual_review";

    // ---- 历史兼容状态（迁移前旧数据，读侧按 in_progress/completed 处理）----
    /** 兼容旧状态：retrying 与 queued 等价 */
    public static final String STATE_RETRYING = "retrying";
    public static final String STATE_DOWNLOADING = "downloading";
    public static final String STATE_VERIFYING = "verifying";
    public static final String STATE_APPLYING = "applying";
    public static final String STATE_SUCCEEDED = "succeeded";

    /** 活跃（非终态）状态：新状态 + 历史兼容状态 */
    public static final Set<String> ACTIVE_STATES = Set.of(
            STATE_QUEUED, STATE_RETRYING, STATE_SENT, STATE_ACCEPTED, STATE_IN_PROGRESS,
            STATE_DOWNLOADING, STATE_VERIFYING, STATE_APPLYING);

    /**
     * 设备重连可重投的状态（需重新签发 URL+signature）。
     * 终态 completed/cancelled/failed/needs_manual_review/expired 永不可重投。
     */
    public static final Set<String> REDELIVERABLE_STATES = Set.of(
            STATE_QUEUED, STATE_RETRYING, STATE_SENT, STATE_ACCEPTED, STATE_IN_PROGRESS,
            STATE_DOWNLOADING, STATE_VERIFYING, STATE_APPLYING);

    /**
     * 管理入口可取消的状态（pending 语义）：尚未完成的非终态任务。
     * pending 无独立落库态，对应 queued/retrying/sent/accepted/in_progress。
     */
    public static final Set<String> CANCELABLE_UPDATE_SPINE_STATES = Set.of(
            STATE_QUEUED, STATE_RETRYING, STATE_SENT, STATE_ACCEPTED, STATE_IN_PROGRESS,
            STATE_DOWNLOADING, STATE_VERIFYING, STATE_APPLYING);

    /** 终态：任何情况下都不得再投递、不得再推进。 */
    public static final Set<String> TERMINAL_STATES = Set.of(
            STATE_COMPLETED, STATE_SUCCEEDED, STATE_FAILED, STATE_EXPIRED,
            STATE_CANCELLED, STATE_NEEDS_MANUAL_REVIEW);

    /** 成功终态（completed / 历史 succeeded），用于幂等 success ACK。 */
    public static final Set<String> SUCCESS_STATES = Set.of(
            STATE_COMPLETED, STATE_SUCCEEDED);

    /** success ACK 允许的前置状态（含 completed 用于幂等）。 */
    public static final Set<String> COMPLETABLE_STATES = Set.of(
            STATE_SENT, STATE_ACCEPTED, STATE_IN_PROGRESS,
            STATE_DOWNLOADING, STATE_VERIFYING, STATE_APPLYING,
            STATE_COMPLETED, STATE_SUCCEEDED);

    /**
     * success 首次完成 CAS 的前置「活跃」状态（不含 completed/succeeded）。
     * 用于 handleSuccessAck 的条件更新：并发第二个 success 时 state 已是 completed，
     * 不再命中该集合 → 影响 0 行 → 走 re-read 幂等分支，保证「最多一次真正迁移」。
     */
    public static final Set<String> COMPLETABLE_ACTIVE_STATES = Set.of(
            STATE_SENT, STATE_ACCEPTED, STATE_IN_PROGRESS,
            STATE_DOWNLOADING, STATE_VERIFYING, STATE_APPLYING);

    public static final String ERR_MAX_REDELIVER = "E_MAX_REDELIVER";
    public static final String ERR_ABNORMAL_DISCONNECT = "E_ABNORMAL_DISCONNECT";
    public static final String ERR_MANUAL_CANCEL = "E_MANUAL_CANCEL";

    public static final String SIG_ALG_ES256 = "ES256";

    public static final String BUNDLE_ROLE_JSON = "role.json";
    public static final String BUNDLE_SKEL = "skeleton.skel";
    public static final String BUNDLE_ATLAS = "skeleton.atlas";
    public static final String BUNDLE_PNG = "texture.png";

    public static final Set<String> BUNDLE_REQUIRED_FILES = Set.of(
            BUNDLE_ROLE_JSON, BUNDLE_SKEL, BUNDLE_ATLAS, BUNDLE_PNG);

    public static final String REDIS_DOWNLOAD_PREFIX = "rolepack:download:";
    public static final String REDIS_DOWNLOAD_COUNT_PREFIX = "rolepack:download:count:";
    public static final String REDIS_PROGRESS_TS_PREFIX = "rolepack:progress:ts:";
    public static final String REDIS_PROGRESS_VAL_PREFIX = "rolepack:progress:val:";

    /** 设备已进入 in_progress 后，重复 waiting 视为幂等忽略 */
    public static final Set<String> IN_FLIGHT_STATES = Set.of(
            STATE_IN_PROGRESS, STATE_DOWNLOADING, STATE_VERIFYING, STATE_APPLYING);

    public static final String CMD_UPDATE_SPINE = "update_spine";
    public static final String MSG_TYPE_SYSTEM = "system";
    public static final String MSG_TYPE_SPINE_OTA_ACK = "spine_ota_ack";

    /** pending 响应内部保留键：领取后的 attempt 版本（controller 剥离后不下发给设备）。 */
    public static final String PENDING_CLAIM_ATTEMPT_KEY = "__claim_attempt";
    /** pending 响应内部保留键：不可复用 lease UUID。 */
    public static final String PENDING_CLAIM_LEASE_KEY = "__claim_lease_id";
    /** pending 响应内部保留键：单调递增 delivery_version。 */
    public static final String PENDING_CLAIM_VERSION_KEY = "__claim_version";
    /** pending 响应内部保留键：领取时的 session_id。 */
    public static final String PENDING_CLAIM_SESSION_KEY = "__claim_session_id";
}
