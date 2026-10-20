package xiaozhi.modules.officialtts.engine;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Base64;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** HMAC media tokens for gateway fetch of clone source audio. */
public final class OfficialTtsMediaToken {
    private OfficialTtsMediaToken() {
    }

    public static String issue(String secret, long userId, long assetId, Instant exp) {
        String payload = userId + "." + assetId + "." + exp.getEpochSecond();
        return payload + "." + sign(secret, payload);
    }

    public static long[] verify(String secret, String token) {
        if (token == null) {
            throw new IllegalArgumentException("media_token_invalid");
        }
        String[] parts = token.split("\\.");
        if (parts.length != 4) {
            throw new IllegalArgumentException("media_token_invalid");
        }
        String payload = parts[0] + "." + parts[1] + "." + parts[2];
        if (!sign(secret, payload).equals(parts[3])) {
            throw new IllegalArgumentException("media_token_invalid");
        }
        long exp = Long.parseLong(parts[2]);
        if (Instant.now().getEpochSecond() > exp) {
            throw new IllegalArgumentException("media_token_expired");
        }
        return new long[] { Long.parseLong(parts[0]), Long.parseLong(parts[1]) };
    }

    private static String sign(String secret, String payload) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            return Base64.getUrlEncoder().withoutPadding()
                    .encodeToString(mac.doFinal(payload.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
