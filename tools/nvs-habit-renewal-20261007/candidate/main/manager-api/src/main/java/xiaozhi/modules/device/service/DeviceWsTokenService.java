package xiaozhi.modules.device.service;

import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.util.Base64;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.constant.Constant;
import xiaozhi.modules.device.util.MacAddressUtils;
import xiaozhi.modules.sys.service.SysParamsService;

/**
 * 设备 WSS token 签发（与 Python {@code core/auth.py} 同构）。
 * WSS token 仅用于 WSS 握手，不得作为 OTA refresh 凭证。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DeviceWsTokenService {

    public static final long DEVICE_TOKEN_TTL_SECONDS = 700L * 24 * 60 * 60;
    public static final String TOKEN_VERSION_V2 = "v2";

    private final SysParamsService sysParamsService;

    public String issueToken(String deviceId, String clientId, long credentialVersion) {
        if (credentialVersion <= 0) {
            throw new IllegalArgumentException("invalid credential version");
        }
        String normalized = MacAddressUtils.toTokenDeviceId(deviceId);
        if (normalized == null) {
            throw new IllegalArgumentException("invalid device id");
        }
        String secret = requireSecret();
        long iat = System.currentTimeMillis() / 1000L;
        long exp = iat + DEVICE_TOKEN_TTL_SECONDS;
        String content = buildV2Canonical(normalized, iat, exp, credentialVersion);
        byte[] sig = hmacSha256(secret, content);
        String sigB64 = Base64.getUrlEncoder().withoutPadding().encodeToString(sig);
        if (clientId == null) {
            // no-op
        }
        return TOKEN_VERSION_V2 + "." + sigB64 + "." + iat + "." + exp + "." + credentialVersion;
    }

    @Deprecated
    public String issueToken(String deviceId, String clientId) {
        throw new IllegalStateException("issueToken requires credentialVersion; use issueToken(deviceId, clientId, version)");
    }

    public static String buildV2Canonical(String normalizedDeviceId, long iat, long exp, long credentialVersion) {
        return TOKEN_VERSION_V2 + "|" + normalizedDeviceId + "|" + iat + "|" + exp + "|" + credentialVersion;
    }

    public static long deviceTokenTtlSeconds() {
        return DEVICE_TOKEN_TTL_SECONDS;
    }

    private String requireSecret() {
        String secret = sysParamsService.getValue(Constant.SERVER_SECRET, true);
        if (StringUtils.isBlank(secret) || "null".equals(secret)) {
            throw new IllegalStateException("server secret not configured");
        }
        return secret;
    }

    private byte[] hmacSha256(String secret, String content) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            return mac.doFinal(content.getBytes(StandardCharsets.UTF_8));
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException("hmac signature failed");
        }
    }
}
