package xiaozhi.modules.face.config;

import java.util.regex.Pattern;

/**
 * face JWT / 租户隔离用的 account_id 规则（与 profile 无关）。
 *
 * <p>合法值：字符串化的智控台 {@code sys_user.id}（数字或安全字母数字）。
 * 禁止：空、default、MAC、device_id、usr_*。
 */
public final class FaceAccountIdRules {

    private static final Pattern SAFE =
            Pattern.compile("^[a-zA-Z0-9_\\-]{1,64}$");
    private static final Pattern MAC_LIKE =
            Pattern.compile("^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$");
    private static final Pattern USR_LIKE =
            Pattern.compile("^usr_[A-Za-z0-9]{4,64}$");

    private FaceAccountIdRules() {
    }

    /**
     * @return 规范化后的 account_id；非法则 null
     */
    public static String normalize(Object raw) {
        if (raw == null) {
            return null;
        }
        String text = String.valueOf(raw).trim();
        if (text.isEmpty() || "0".equals(text) || "null".equalsIgnoreCase(text)
                || "None".equals(text)) {
            return null;
        }
        if (isReserved(text)) {
            return null;
        }
        if (!SAFE.matcher(text).matches()) {
            return null;
        }
        return text;
    }

    public static boolean isReserved(String text) {
        if (text == null || text.isBlank()) {
            return true;
        }
        String t = text.trim();
        if ("default".equalsIgnoreCase(t)) {
            return true;
        }
        if (MAC_LIKE.matcher(t).matches()) {
            return true;
        }
        if (USR_LIKE.matcher(t).matches()) {
            return true;
        }
        return false;
    }

    public static boolean isValidRuntimeAccountId(String text) {
        return normalize(text) != null;
    }
}
