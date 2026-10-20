package xiaozhi.modules.officialtts.engine;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

import xiaozhi.common.utils.JsonUtils;

/**
 * Talks to the isolated/native bailian gateway. Billing happens in the gateway ledger.
 */
public class OfficialTtsGatewayClient {
    private final String baseUrl;

    public OfficialTtsGatewayClient(String baseUrl) {
        if (baseUrl == null || baseUrl.isBlank()) {
            throw new IllegalStateException("gateway_base_required");
        }
        this.baseUrl = baseUrl.replaceAll("/+$", "");
    }

    public Map<String, Object> cloneVoice(String token, String idem, Map<String, Object> body) {
        return json("POST", "/bailian/v1/voices/clone", token, idem, body);
    }

    public Map<String, Object> designVoice(String token, String idem, Map<String, Object> body) {
        return json("POST", "/bailian/v1/voices/design", token, idem, body);
    }

    public Map<String, Object> voiceTask(String token, String taskId) {
        return json("GET", "/bailian/v1/voices/tasks/" + taskId, token, null, null);
    }

    public Map<String, Object> deleteVoice(String token, String voiceId) {
        return json("DELETE", "/bailian/v1/voices/" + encodePathSegment(voiceId), token, null, null);
    }

    public Map<String, Object> synthesize(String token, String idem, Map<String, Object> body) {
        return json("POST", "/bailian/v1/synthesis", token, idem, body);
    }

    public Map<String, Object> cancel(String token, String billId) {
        return json("POST", "/bailian/v1/synthesis/cancel", token, null, Map.of("bill_id", billId));
    }

    public Map<String, Object> adminResolve(String token, String billId, Map<String, Object> body) {
        return json("POST", "/bailian/v1/bills/" + billId + "/admin-resolve", token, null, body);
    }

    public Map<String, Object> adminNote(String token, String billId, Map<String, Object> body) {
        return json("POST", "/bailian/v1/bills/" + billId + "/admin-note", token, null, body);
    }

    public Map<String, Object> getBill(String token, String billId) {
        return json("GET", "/bailian/v1/bills/" + billId, token, null, null);
    }

    public Map<String, Object> publishPrices(String token, Map<String, Object> body) {
        return json("POST", "/bailian/v1/prices/publish", token, null, body);
    }

    public Map<String, Object> publishedPrices(String token) {
        return json("GET", "/bailian/v1/prices/published", token, null, null);
    }

    private static String encodePathSegment(String raw) {
        if (raw == null || raw.isBlank()) {
            return "";
        }
        try {
            return java.net.URLEncoder.encode(raw, StandardCharsets.UTF_8).replace("+", "%20");
        } catch (Exception e) {
            return raw;
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> json(String method, String path, String token, String idem, Map<String, Object> body) {
        try {
            HttpURLConnection conn = (HttpURLConnection) URI.create(baseUrl + path).toURL().openConnection();
            conn.setConnectTimeout(5000);
            conn.setReadTimeout(25000);
            conn.setRequestMethod(method);
            conn.setRequestProperty("Authorization", bearer(token));
            conn.setRequestProperty("Accept", "application/json");
            if (idem != null && !idem.isBlank()) {
                conn.setRequestProperty("Idempotency-Key", idem);
            }
            if (body != null && !"GET".equals(method) && !"DELETE".equals(method)) {
                byte[] payload = JsonUtils.toJsonString(body).getBytes(StandardCharsets.UTF_8);
                conn.setDoOutput(true);
                conn.setRequestProperty("Content-Type", "application/json");
                try (OutputStream os = conn.getOutputStream()) {
                    os.write(payload);
                }
            } else if ("DELETE".equals(method) && body != null) {
                conn.setDoOutput(true);
            }
            int code = conn.getResponseCode();
            InputStream in = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
            String raw = read(in);
            Map<String, Object> parsed = JsonUtils.parseObject(raw, Map.class);
            if (parsed == null) {
                parsed = new HashMap<>();
            }
            parsed.put("_http", code);
            parsed.put("_raw", raw);
            if (code >= 400) {
                throw new IllegalStateException("gateway_http_" + code + ":" + parsed.getOrDefault("error", raw));
            }
            return parsed;
        } catch (IllegalStateException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException("gateway_unreachable:" + e.getMessage(), e);
        }
    }

    private static String bearer(String token) {
        if (token == null) {
            throw new IllegalStateException("customer_token_required");
        }
        String t = token.trim();
        return t.startsWith("Bearer ") ? t : (t.startsWith("sk-") ? "Bearer " + t : "Bearer sk-" + t);
    }

    private static String read(InputStream in) throws Exception {
        if (in == null) {
            return "{}";
        }
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        in.transferTo(out);
        return out.toString(StandardCharsets.UTF_8);
    }
}
