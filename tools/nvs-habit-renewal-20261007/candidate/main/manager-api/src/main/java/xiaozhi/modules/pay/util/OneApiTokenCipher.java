package xiaozhi.modules.pay.util;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/**
 * one-api 设备 token 的 AES-256-GCM 加解密工具。
 *
 * 密文格式：base64( IV[12] || ciphertext || tag[16] )，每次加密随机生成 IV。
 * 密钥为 32 字节（hex 64 字符），从环境变量 / secrets 文件注入，禁止硬编码。
 */
public final class OneApiTokenCipher {

    private static final String TRANSFORMATION = "AES/GCM/NoPadding";
    private static final int IV_LENGTH = 12;
    private static final int TAG_LENGTH_BITS = 128;
    private static final SecureRandom RANDOM = new SecureRandom();

    private OneApiTokenCipher() {
    }

    /**
     * AES-256-GCM 加密，返回 base64 密文。
     *
     * @param keyHex    32 字节 hex 密钥（64 字符）
     * @param plainText 待加密明文（token key）
     */
    public static String encrypt(String keyHex, String plainText) {
        SecretKeySpec key = keySpec(keyHex);
        try {
            byte[] iv = new byte[IV_LENGTH];
            RANDOM.nextBytes(iv);

            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            cipher.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(TAG_LENGTH_BITS, iv));
            byte[] encrypted = cipher.doFinal(plainText.getBytes(StandardCharsets.UTF_8));

            byte[] out = new byte[IV_LENGTH + encrypted.length];
            System.arraycopy(iv, 0, out, 0, IV_LENGTH);
            System.arraycopy(encrypted, 0, out, IV_LENGTH, encrypted.length);
            return Base64.getEncoder().encodeToString(out);
        } catch (Exception e) {
            throw new IllegalStateException("one-api token 加密失败", e);
        }
    }

    /**
     * AES-256-GCM 解密，返回明文 token key。
     */
    public static String decrypt(String keyHex, String cipherText) {
        SecretKeySpec key = keySpec(keyHex);
        try {
            byte[] data = Base64.getDecoder().decode(cipherText);
            if (data.length < IV_LENGTH + 16) {
                throw new IllegalArgumentException("密文长度非法");
            }

            byte[] iv = new byte[IV_LENGTH];
            System.arraycopy(data, 0, iv, 0, IV_LENGTH);

            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(TAG_LENGTH_BITS, iv));
            byte[] decrypted = cipher.doFinal(data, IV_LENGTH, data.length - IV_LENGTH);
            return new String(decrypted, StandardCharsets.UTF_8);
        } catch (Exception e) {
            throw new IllegalStateException("one-api token 解密失败", e);
        }
    }

    /**
     * 计算 token key 的 SHA-256 指纹（hex），用于轮换检测。
     */
    public static String fingerprint(String plainTokenKey) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(plainTokenKey.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(digest.length * 2);
            for (byte b : digest) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new IllegalStateException("计算指纹失败", e);
        }
    }

    private static SecretKeySpec keySpec(String keyHex) {
        if (keyHex == null || keyHex.length() != 64) {
            throw new IllegalArgumentException("AES-256 密钥必须为 64 字符 hex");
        }
        byte[] keyBytes = new byte[32];
        for (int i = 0; i < 32; i++) {
            int hi = Character.digit(keyHex.charAt(i * 2), 16);
            int lo = Character.digit(keyHex.charAt(i * 2 + 1), 16);
            if (hi < 0 || lo < 0) {
                throw new IllegalArgumentException("密钥包含非法 hex 字符");
            }
            keyBytes[i] = (byte) ((hi << 4) | lo);
        }
        return new SecretKeySpec(keyBytes, "AES");
    }
}
