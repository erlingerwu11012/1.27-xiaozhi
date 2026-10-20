package xiaozhi.modules.device.util;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * 设备级 bootstrap 密钥：生成与常量时间校验。
 * 存储仅为 HMAC-SHA256(serverSecret, plaintext) 的 hex，绝不落库明文。
 */
public final class DeviceBootstrapCrypto {

    private static final SecureRandom RANDOM = new SecureRandom();

    private DeviceBootstrapCrypto() {
    }

    /** 生成 32 字节随机密钥，base64url 无 padding。 */
    public static String generatePlaintext() {
        byte[] raw = new byte[32];
        RANDOM.nextBytes(raw);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(raw);
    }

    public static String hash(String serverSecret, String plaintext) {
        if (serverSecret == null || plaintext == null) {
            throw new IllegalArgumentException("missing secret material");
        }
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(serverSecret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] dig = mac.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
            return toHex(dig);
        } catch (Exception e) {
            throw new IllegalStateException("bootstrap hash failed");
        }
    }

    /** 常量时间比较：presented 明文与 storedHash 是否匹配。 */
    public static boolean matches(String serverSecret, String plaintext, String storedHash) {
        if (serverSecret == null || plaintext == null || storedHash == null || storedHash.isEmpty()) {
            return false;
        }
        String computed = hash(serverSecret, plaintext);
        byte[] a = computed.getBytes(StandardCharsets.UTF_8);
        byte[] b = storedHash.getBytes(StandardCharsets.UTF_8);
        return MessageDigest.isEqual(a, b);
    }

    private static String toHex(byte[] bytes) {
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) {
            sb.append(String.format("%02x", value));
        }
        return sb.toString();
    }
}
