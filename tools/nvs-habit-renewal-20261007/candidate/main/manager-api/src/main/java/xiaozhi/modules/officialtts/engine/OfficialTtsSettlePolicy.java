package xiaozhi.modules.officialtts.engine;

/**
 * Manual settle is a funds movement. Notes must never call this policy.
 * finalTotal is the cumulative charged amount, not an increment.
 */
public final class OfficialTtsSettlePolicy {
    private OfficialTtsSettlePolicy() {
    }

    public static void requireNote(String operationId, String reason) {
        if (blank(operationId)) {
            throw new IllegalArgumentException("operation_id_required");
        }
        if (blank(reason)) {
            throw new IllegalArgumentException("note_reason_required");
        }
    }

    public static void requireSettle(Long finalTotal, boolean present, boolean confirmZero, String operationId,
            String reason, String evidence) {
        if (blank(operationId)) {
            throw new IllegalArgumentException("operation_id_required");
        }
        if (blank(reason) || blank(evidence)) {
            throw new IllegalArgumentException("admin_reason_and_evidence_required");
        }
        if (!present || finalTotal == null) {
            throw new IllegalArgumentException("final_total_required");
        }
        if (finalTotal < 0) {
            throw new IllegalArgumentException("final_total_invalid");
        }
        if (finalTotal == 0 && !confirmZero) {
            throw new IllegalArgumentException("confirm_zero_required");
        }
    }

    public static void assertNotBelowCharged(long charged, long finalTotal) {
        if (finalTotal < charged) {
            throw new IllegalStateException("cannot_reduce_below_confirmed");
        }
    }

    public static long additionalCharge(long charged, long finalTotal) {
        return finalTotal - charged;
    }

    public static long expectedRelease(long charged, long held, long finalTotal) {
        return held - (finalTotal - charged);
    }

    private static boolean blank(String s) {
        return s == null || s.trim().isEmpty();
    }
}
