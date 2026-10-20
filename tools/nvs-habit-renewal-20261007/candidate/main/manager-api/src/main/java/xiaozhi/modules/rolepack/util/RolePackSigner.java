package xiaozhi.modules.rolepack.util;

import java.math.BigInteger;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.Signature;
import java.security.interfaces.ECPrivateKey;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.util.Arrays;
import java.util.Base64;
import java.util.Locale;

import org.apache.commons.lang3.StringUtils;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.stereotype.Component;

import jakarta.annotation.PostConstruct;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.rolepack.config.RolePackProperties;

/**
 * ES256 任务签名：canonical 与固件 scripts/sign_spine_task.py 逐字节一致；
 * 输出 raw 64-byte r||s 的 base64（非 DER）。
 * <p>
 * 启动时从私钥推导公钥指纹，与 ROLE_PACK_EXPECTED_PUBLIC_KEY_SHA256 比对；
 * 不一致或缺失时 fail-closed。此组件永不生成 ephemeral key。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class RolePackSigner {

    private final RolePackProperties properties;
    private final Environment environment;

    @Getter
    private PrivateKey privateKey;

    @Getter
    private PublicKey publicKey;

    @Getter
    private String publicKeySha256;

    private boolean ready;
    private boolean fingerprintMatched;

    @PostConstruct
    public void init() {
        fingerprintMatched = false;
        ready = false;
        publicKey = null;
        publicKeySha256 = null;
        try {
            String pem = System.getenv("ROLE_PACK_SIGNING_PRIVATE_KEY_PEM");
            if (StringUtils.isBlank(pem)) {
                pem = properties.getSigningPrivateKeyPem();
            }
            if (StringUtils.isBlank(pem) && StringUtils.isNotBlank(properties.getSigningPrivateKeyPath())) {
                pem = Files.readString(Path.of(properties.getSigningPrivateKeyPath()));
            }
            if (StringUtils.isNotBlank(pem)) {
                this.privateKey = loadPrivateKey(pem);
                this.publicKey = derivePublicKey((ECPrivateKey) privateKey);
                this.publicKeySha256 = sha256HexOfPublicKey(publicKey);
                verifyExpectedFingerprint();
                this.ready = fingerprintMatched;
                if (ready) {
                    log.info("RolePackSigner: ES256 私钥已加载，公钥指纹={}", publicKeySha256);
                }
                return;
            }

            boolean prod = isProductionProfile();
            if (prod) {
                log.error("RolePackSigner: 生产环境缺少 ROLE_PACK_SIGNING_PRIVATE_KEY_PEM，发布/部署将 fail-closed");
                return;
            }
            log.warn("RolePackSigner: 未配置签名私钥，发布/部署将失败");
        } catch (Exception e) {
            this.ready = false;
            log.error("RolePackSigner 初始化失败: {}", e.getMessage());
        }
    }

    private void verifyExpectedFingerprint() {
        String expected = System.getenv("ROLE_PACK_EXPECTED_PUBLIC_KEY_SHA256");
        if (StringUtils.isBlank(expected)) {
            expected = properties.getExpectedPublicKeySha256();
        }
        if (StringUtils.isBlank(expected)) {
            fingerprintMatched = false;
            ready = false;
            log.error("RolePackSigner: 缺少 ROLE_PACK_EXPECTED_PUBLIC_KEY_SHA256，无法证明与固件公钥配对，fail-closed");
            return;
        }
        String norm = expected.trim().toLowerCase(Locale.ROOT).replace(":", "");
        if (!norm.equals(publicKeySha256)) {
            fingerprintMatched = false;
            ready = false;
            log.error("RolePackSigner: 公钥指纹不匹配 expected={} actual={} — 发布/部署 fail-closed（需与固件内置公钥成对更换）",
                    norm, publicKeySha256);
            return;
        }
        fingerprintMatched = true;
    }

    private boolean isProductionProfile() {
        if (environment == null) {
            return false;
        }
        return environment.acceptsProfiles(Profiles.of("prod", "production"));
    }

    public boolean isReady() {
        return ready && privateKey != null && fingerprintMatched;
    }

    public void requireReady() {
        if (isProductionProfile() && !isReady()) {
            throw new RenException("生产环境缺少配对签名私钥或公钥指纹不匹配（ROLE_PACK_SIGNING_PRIVATE_KEY_PEM / ROLE_PACK_EXPECTED_PUBLIC_KEY_SHA256）");
        }
        if (!isReady()) {
            throw new RenException(
                    "角色包签名未就绪：请设置 ROLE_PACK_SIGNING_PRIVATE_KEY_PEM 与 ROLE_PACK_EXPECTED_PUBLIC_KEY_SHA256（须与固件公钥一致）");
        }
    }

    /**
     * 客户端唯一 canonical（每行裸值，末行为 https origin+path，无 query）：
     * task_id\n pack_id\n role_id\n version\n size\n sha256\n min_fw\n https://host/path\n
     */
    public static String buildCanonicalPayload(String taskId, String packId, String roleId,
            String version, long size, String sha256, String minFw, String downloadUrl) {
        String signedUrl = extractSignedUrlOriginPath(downloadUrl);
        return nullToEmpty(taskId) + "\n"
                + nullToEmpty(packId) + "\n"
                + nullToEmpty(roleId) + "\n"
                + nullToEmpty(version) + "\n"
                + size + "\n"
                + nullToEmpty(sha256).toLowerCase(Locale.ROOT) + "\n"
                + nullToEmpty(minFw) + "\n"
                + signedUrl + "\n";
    }

    /**
     * 从完整下载 URL 提取参与签名的 https://&lt;lowercase-host&gt;&lt;path&gt;（去掉 query/fragment/端口）。
     */
    public static String extractSignedUrlOriginPath(String downloadUrl) {
        if (StringUtils.isBlank(downloadUrl)) {
            throw new RenException("下载 URL 不能为空");
        }
        URI uri;
        try {
            uri = URI.create(downloadUrl.trim());
        } catch (Exception e) {
            throw new RenException("下载 URL 非法");
        }
        String scheme = uri.getScheme();
        if (scheme == null || !"https".equalsIgnoreCase(scheme)) {
            throw new RenException("下载 URL 必须使用 https");
        }
        if (uri.getUserInfo() != null) {
            throw new RenException("下载 URL 禁止 userinfo");
        }
        if (uri.getFragment() != null) {
            throw new RenException("下载 URL 禁止 fragment");
        }
        if (uri.getPort() != -1) {
            throw new RenException("下载 URL 禁止显式端口");
        }
        String host = uri.getHost();
        if (StringUtils.isBlank(host)) {
            throw new RenException("下载 URL 缺少 host");
        }
        host = host.toLowerCase(Locale.ROOT);
        if (isIpLiteral(host)) {
            throw new RenException("下载 URL 禁止 IP literal");
        }
        String path = uri.getRawPath();
        if (StringUtils.isBlank(path)) {
            path = "/";
        }
        return "https://" + host + path;
    }

    public static boolean isIpLiteral(String host) {
        if (host == null) {
            return true;
        }
        if (host.matches("\\d{1,3}(\\.\\d{1,3}){3}")) {
            return true;
        }
        return host.contains(":");
    }

    public String signTask(String taskId, String packId, String roleId, String version,
            long size, String sha256, String minFw, String downloadUrl) {
        return sign(buildCanonicalPayload(taskId, packId, roleId, version, size, sha256, minFw, downloadUrl));
    }

    /**
     * 壁纸 OTA 任务签名：canonical 第三行固定为字面量 {@code wallpaper}。
     */
    public String signWallpaperTask(String taskId, String packId, String version,
            long size, String sha256, String minFw, String downloadUrl) {
        return sign(buildCanonicalPayload(taskId, packId, RolePackSigner.WALLPAPER_RESOURCE_IDENTITY,
                version, size, sha256, minFw, downloadUrl));
    }

    /**
     * 壁纸包级审计签名：task_id 为空行，第三行固定 {@code wallpaper}。
     */
    public String signWallpaperPack(String packId, String version, long size,
            String sha256, String minFw, String contentHttpsUrl) {
        return sign(buildCanonicalPayload("", packId, WALLPAPER_RESOURCE_IDENTITY,
                version, size, sha256, minFw, contentHttpsUrl));
    }

    /** 壁纸 canonical 第三行固定字面量（禁止调用方传入其它值）。 */
    public static final String WALLPAPER_RESOURCE_IDENTITY = "wallpaper";

    /**
     * 包级审计签名：task_id 为空行，URL 使用稳定 content 路径（无 token）。
     */
    public String signPack(String packId, String roleId, String version, long size,
            String sha256, String minFw, String contentHttpsUrl) {
        return sign(buildCanonicalPayload("", packId, roleId, version, size, sha256, minFw, contentHttpsUrl));
    }

    public String sign(String canonical) {
        requireReady();
        try {
            Signature sig = Signature.getInstance("SHA256withECDSA");
            sig.initSign(privateKey);
            sig.update(canonical.getBytes(StandardCharsets.UTF_8));
            byte[] der = sig.sign();
            byte[] raw = derToRawRs(der, 32);
            String b64 = Base64.getEncoder().encodeToString(raw);
            if (b64.length() != 88) {
                throw new RenException("raw r||s base64 长度异常: " + b64.length());
            }
            return b64;
        } catch (RenException e) {
            throw e;
        } catch (Exception e) {
            throw new RenException("角色包签名失败: " + e.getMessage());
        }
    }

    public static boolean verify(PublicKey publicKey, String canonical, String signatureBase64) throws Exception {
        byte[] sigBytes = Base64.getDecoder().decode(signatureBase64);
        byte[] der;
        if (sigBytes.length == 64) {
            der = rawRsToDer(sigBytes);
        } else {
            der = sigBytes;
        }
        Signature sig = Signature.getInstance("SHA256withECDSA");
        sig.initVerify(publicKey);
        sig.update(canonical.getBytes(StandardCharsets.UTF_8));
        return sig.verify(der);
    }

    public static PublicKey derivePublicKey(ECPrivateKey privateKey) throws Exception {
        org.bouncycastle.jce.spec.ECParameterSpec bcSpec =
                org.bouncycastle.jce.ECNamedCurveTable.getParameterSpec("secp256r1");
        org.bouncycastle.math.ec.ECPoint q = bcSpec.getG().multiply(privateKey.getS()).normalize();
        org.bouncycastle.jce.spec.ECPublicKeySpec pubSpec =
                new org.bouncycastle.jce.spec.ECPublicKeySpec(q, bcSpec);
        PublicKey bcKey = KeyFactory.getInstance("EC", new org.bouncycastle.jce.provider.BouncyCastleProvider())
                .generatePublic(pubSpec);
        // 归一化为平台默认 EC 编码，保证与 openssl -pubout -outform DER 指纹一致
        return KeyFactory.getInstance("EC").generatePublic(new X509EncodedKeySpec(bcKey.getEncoded()));
    }

    public static String sha256HexOfPublicKey(PublicKey publicKey) throws Exception {
        byte[] encoded = publicKey.getEncoded(); // X.509 SubjectPublicKeyInfo
        byte[] dig = MessageDigest.getInstance("SHA-256").digest(encoded);
        StringBuilder sb = new StringBuilder(dig.length * 2);
        for (byte b : dig) {
            sb.append(String.format("%02x", b));
        }
        return sb.toString();
    }

    public static PublicKey loadPublicKey(String pem) throws Exception {
        String normalized = pem
                .replace("-----BEGIN PUBLIC KEY-----", "")
                .replace("-----END PUBLIC KEY-----", "")
                .replaceAll("\\s", "");
        byte[] decoded = Base64.getDecoder().decode(normalized);
        return KeyFactory.getInstance("EC").generatePublic(new X509EncodedKeySpec(decoded));
    }

    public static PrivateKey loadPrivateKey(String pem) throws Exception {
        String normalized = pem
                .replace("-----BEGIN PRIVATE KEY-----", "")
                .replace("-----END PRIVATE KEY-----", "")
                .replaceAll("\\s", "");
        if (pem.contains("BEGIN EC PRIVATE KEY")) {
            throw new IllegalArgumentException("请使用 PKCS#8 PEM（BEGIN PRIVATE KEY），不要使用 SEC1 EC PRIVATE KEY");
        }
        byte[] decoded = Base64.getDecoder().decode(normalized);
        PKCS8EncodedKeySpec spec = new PKCS8EncodedKeySpec(decoded);
        PrivateKey key = KeyFactory.getInstance("EC").generatePrivate(spec);
        if (!(key instanceof ECPrivateKey)) {
            throw new IllegalArgumentException("不是 EC 私钥");
        }
        return key;
    }

    /** DER ECDSA → IEEE P1363 r||s（各 coordLen 字节） */
    public static byte[] derToRawRs(byte[] der, int coordLen) {
        int idx = 0;
        if (der[idx++] != 0x30) {
            throw new IllegalArgumentException("非 DER SEQUENCE");
        }
        int seqLen = der[idx++] & 0xFF;
        if ((seqLen & 0x80) != 0) {
            int n = seqLen & 0x7F;
            seqLen = 0;
            for (int i = 0; i < n; i++) {
                seqLen = (seqLen << 8) | (der[idx++] & 0xFF);
            }
        }
        if (der[idx++] != 0x02) {
            throw new IllegalArgumentException("缺少 r INTEGER");
        }
        int rLen = der[idx++] & 0xFF;
        byte[] r = Arrays.copyOfRange(der, idx, idx + rLen);
        idx += rLen;
        if (der[idx++] != 0x02) {
            throw new IllegalArgumentException("缺少 s INTEGER");
        }
        int sLen = der[idx++] & 0xFF;
        byte[] s = Arrays.copyOfRange(der, idx, idx + sLen);
        byte[] out = new byte[coordLen * 2];
        writePadded(r, out, 0, coordLen);
        writePadded(s, out, coordLen, coordLen);
        return out;
    }

    public static byte[] rawRsToDer(byte[] raw) {
        if (raw.length != 64) {
            throw new IllegalArgumentException("raw r||s 必须 64 字节");
        }
        byte[] r = Arrays.copyOfRange(raw, 0, 32);
        byte[] s = Arrays.copyOfRange(raw, 32, 64);
        byte[] rEnc = stripLeadingZeros(r);
        byte[] sEnc = stripLeadingZeros(s);
        if ((rEnc[0] & 0x80) != 0) {
            rEnc = concat(new byte[] { 0 }, rEnc);
        }
        if ((sEnc[0] & 0x80) != 0) {
            sEnc = concat(new byte[] { 0 }, sEnc);
        }
        int len = 2 + rEnc.length + 2 + sEnc.length;
        byte[] der = new byte[2 + len];
        der[0] = 0x30;
        der[1] = (byte) len;
        int i = 2;
        der[i++] = 0x02;
        der[i++] = (byte) rEnc.length;
        System.arraycopy(rEnc, 0, der, i, rEnc.length);
        i += rEnc.length;
        der[i++] = 0x02;
        der[i++] = (byte) sEnc.length;
        System.arraycopy(sEnc, 0, der, i, sEnc.length);
        return der;
    }

    private static void writePadded(byte[] value, byte[] dest, int destOff, int len) {
        BigInteger bi = new BigInteger(1, value);
        byte[] unsigned = bi.toByteArray();
        Arrays.fill(dest, destOff, destOff + len, (byte) 0);
        if (unsigned.length >= len) {
            System.arraycopy(unsigned, unsigned.length - len, dest, destOff, len);
        } else {
            System.arraycopy(unsigned, 0, dest, destOff + (len - unsigned.length), unsigned.length);
        }
    }

    private static byte[] stripLeadingZeros(byte[] in) {
        int i = 0;
        while (i < in.length - 1 && in[i] == 0) {
            i++;
        }
        return Arrays.copyOfRange(in, i, in.length);
    }

    private static byte[] concat(byte[] a, byte[] b) {
        byte[] c = new byte[a.length + b.length];
        System.arraycopy(a, 0, c, 0, a.length);
        System.arraycopy(b, 0, c, a.length, b.length);
        return c;
    }

    private static String nullToEmpty(String s) {
        return s == null ? "" : s;
    }
}
