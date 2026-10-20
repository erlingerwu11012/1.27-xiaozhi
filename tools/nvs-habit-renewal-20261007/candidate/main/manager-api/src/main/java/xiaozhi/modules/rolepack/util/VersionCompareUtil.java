package xiaozhi.modules.rolepack.util;

import org.apache.commons.lang3.StringUtils;

/**
 * SemVer-ish 分段比较（与 DeviceServiceImpl.compareVersions 行为一致）。
 */
public final class VersionCompareUtil {

    private VersionCompareUtil() {
    }

    public static boolean isValidSemVerLike(String version) {
        if (StringUtils.isBlank(version)) {
            return false;
        }
        return version.matches("\\d+(\\.\\d+){0,3}([-_][A-Za-z0-9.]+)?");
    }

    /**
     * @return v1>v2 → 1；v1&lt;v2 → -1；相等 → 0
     */
    public static int compare(String version1, String version2) {
        if (version1 == null) {
            version1 = "0.0.0";
        }
        if (version2 == null) {
            version2 = "0.0.0";
        }
        String v1 = version1.split("[-_]")[0];
        String v2 = version2.split("[-_]")[0];
        String[] a = v1.split("\\.");
        String[] b = v2.split("\\.");
        int len = Math.max(a.length, b.length);
        for (int i = 0; i < len; i++) {
            int x = i < a.length ? parsePart(a[i]) : 0;
            int y = i < b.length ? parsePart(b[i]) : 0;
            if (x != y) {
                return Integer.compare(x, y);
            }
        }
        return 0;
    }

    private static int parsePart(String s) {
        try {
            return Integer.parseInt(s.replaceAll("[^0-9].*$", "").isEmpty()
                    ? "0"
                    : s.replaceAll("[^0-9].*$", ""));
        } catch (Exception e) {
            return 0;
        }
    }
}
