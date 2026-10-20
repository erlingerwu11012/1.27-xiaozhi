package xiaozhi.modules.officialtts.engine;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * Server-side voice ACL. Client flags such as voice_owner_ok are ignored.
 */
public final class OfficialTtsVoiceAcl {
    public static final List<String> SYSTEM_VOICES = List.of("longanlingxi", "longanqian");

    private OfficialTtsVoiceAcl() {
    }

    public static List<String> allowedCodes(List<String> ownedAvailableUpstreamIds) {
        Set<String> out = new LinkedHashSet<>(SYSTEM_VOICES);
        if (ownedAvailableUpstreamIds != null) {
            for (String id : ownedAvailableUpstreamIds) {
                if (id != null && !id.isBlank()) {
                    out.add(id.trim());
                }
            }
        }
        return new ArrayList<>(out);
    }

    public static void require(String voice, List<String> allowed) {
        if (!isAllowed(voice, allowed)) {
            throw new IllegalArgumentException("voice_not_authorized:" + voice);
        }
    }

    public static boolean isAllowed(String voice, List<String> allowed) {
        if (voice == null || voice.isBlank()) {
            return false;
        }
        String code = voice.trim();
        List<String> list = allowed == null ? SYSTEM_VOICES : allowed;
        for (String item : list) {
            if (code.equals(item)) {
                return true;
            }
        }
        return false;
    }

    public static boolean isSystem(String voice) {
        return SYSTEM_VOICES.contains(voice);
    }

    public static String payloadHash(String canonicalJson) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] d = md.digest(canonicalJson.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(64);
            for (byte b : d) {
                sb.append(String.format(Locale.ROOT, "%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
