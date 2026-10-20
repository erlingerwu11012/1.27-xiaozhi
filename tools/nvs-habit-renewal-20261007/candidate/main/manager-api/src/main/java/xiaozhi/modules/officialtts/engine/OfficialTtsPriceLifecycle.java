package xiaozhi.modules.officialtts.engine;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Objects;

/**
 * Java-side sale price lifecycle. Published rows are immutable; a new draft
 * gets a new version. Gateway enabled version is the debit authority.
 */
public final class OfficialTtsPriceLifecycle {
    public static final String DRAFT = "draft";
    public static final String ACTIVE = "active";
    public static final String HISTORY = "published_history";
    public static final String FAILED = "publish_failed";
    public static final String ACK_PENDING = "publish_ack_pending";
    public static final String COST_PENDING = "pricing_pending";

    public static final String UNIT_HINT_SALE = "CNY per metered unit (weighted_character or count); converted to quota by gateway QuotaPerUSD/CNYPerUSD";
    public static final String UNIT_HINT_COST = "Aliyun cost CNY per unit; never used as customer debit";

    private OfficialTtsPriceLifecycle() {
    }

    public static boolean isPublishedLocked(String status) {
        return ACTIVE.equals(status) || HISTORY.equals(status) || ACK_PENDING.equals(status);
    }

    public static void assertDraftMutable(String status) {
        if (isPublishedLocked(status)) {
            throw new IllegalStateException("published_immutable");
        }
    }

    public static String nextVersion(String model, String region, List<String> existing) {
        if (model == null || region == null || !model.equals(OfficialTtsPriceGate.MODEL)
                || !region.equals(OfficialTtsPriceGate.REGION)) {
            throw new IllegalArgumentException("price_identity_required");
        }
        int max = 0;
        if (existing != null) {
            for (String v : existing) {
                if (v == null) {
                    continue;
                }
                String[] parts = v.split("\\|", -1);
                if (parts.length != 3 || !model.equals(parts[0]) || !region.equals(parts[1])) {
                    continue;
                }
                String tail = parts[2];
                if (tail.startsWith("v")) {
                    try {
                        max = Math.max(max, Integer.parseInt(tail.substring(1)));
                    } catch (NumberFormatException ignored) {
                        // ignore non-numeric tails
                    }
                }
            }
        }
        return model + "|" + region + "|v" + (max + 1);
    }

    public static String classify(String javaStatus, String javaVersion, String gatewayEnabledVersion) {
        if (COST_PENDING.equals(javaStatus)) {
            return "cost_placeholder";
        }
        if (DRAFT.equals(javaStatus)) {
            return "draft";
        }
        if (FAILED.equals(javaStatus)) {
            return "publish_failed";
        }
        if (ACK_PENDING.equals(javaStatus)) {
            return "publish_ack_pending";
        }
        if (HISTORY.equals(javaStatus)) {
            return "published_history";
        }
        if (ACTIVE.equals(javaStatus)) {
            if (javaVersion != null && javaVersion.equals(gatewayEnabledVersion)) {
                return "active_confirmed";
            }
            if (gatewayEnabledVersion == null || gatewayEnabledVersion.isBlank()) {
                return "publish_ack_pending";
            }
            return "active_mismatch";
        }
        return javaStatus == null ? "unknown" : javaStatus.toLowerCase(Locale.ROOT);
    }

    public static List<String> versionsOf(List<String> rows) {
        return rows == null ? List.of() : new ArrayList<>(rows);
    }

    public static boolean sameVersion(String a, String b) {
        return Objects.equals(a, b);
    }
}
