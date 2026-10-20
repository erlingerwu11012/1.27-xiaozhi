package xiaozhi.modules.device.util;

/**
 * 设备 MAC 地址统一规范化工具。
 *
 * <p>设备身份（绑定主键）统一为小写、去掉 ':' 与 '-' 分隔符后的 12 位 hex。
 * 供 OTAController / DeviceServiceImpl / DeviceWsTokenService 共用，避免各处各自猜测格式。
 */
public final class MacAddressUtils {

    private static final String HEX12 = "^[0-9a-f]{12}$";

    private MacAddressUtils() {
    }

    /**
     * 规范化核心：去空白、转小写、去掉 ':' 与 '-' 分隔符，得到 12 位 hex；非法返回 null。
     */
    public static String normalize(String mac) {
        if (mac == null) {
            return null;
        }
        String s = mac.trim().toLowerCase().replace(":", "").replace("-", "");
        return s.matches(HEX12) ? s : null;
    }

    /**
     * 是否为合法 MAC（支持大小写、带/不带 ':' 或 '-' 分隔符）。
     */
    public static boolean isValid(String mac) {
        return normalize(mac) != null;
    }

    /**
     * 数据库规范格式：小写 + 冒号分隔，如 {@code aa:bb:cc:dd:ee:ff}。
     */
    public static String toCanonical(String mac) {
        String n = normalize(mac);
        if (n == null) {
            return null;
        }
        return n.substring(0, 2) + ":" + n.substring(2, 4) + ":" + n.substring(4, 6) + ":"
                + n.substring(6, 8) + ":" + n.substring(8, 10) + ":" + n.substring(10, 12);
    }

    /**
     * token 签名内容所用的 device_id 形式：小写 12 位 hex（无分隔符）。
     * 与 Python AuthManager.normalize_device_id 保持一致。
     */
    public static String toTokenDeviceId(String mac) {
        return normalize(mac);
    }
}
