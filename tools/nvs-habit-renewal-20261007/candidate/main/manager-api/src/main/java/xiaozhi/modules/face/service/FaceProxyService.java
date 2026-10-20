package xiaozhi.modules.face.service;

import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;

import cn.hutool.jwt.JWTUtil;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.face.config.FaceAccountIdRules;
import xiaozhi.modules.face.config.FaceProperties;
import xiaozhi.modules.security.user.SecurityUser;

/**
 * 受保护的 face-api 代理：用服务间 JWT 访问，不把 manager 登录 token 当作 face JWT。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class FaceProxyService {

    private final FaceProperties faceProperties;
    private final RestTemplate restTemplate;

    /** 仅用于日志；JWT 门禁不再依赖 profile。 */
    @Value("${spring.profiles.active:prod}")
    private String activeProfile;

    public Object listProfiles(boolean includeDraft) {
        ensureConfigured();
        String url = base() + "/face/profiles?include_draft=" + includeDraft + "&ensure_owner=false";
        return exchange(HttpMethod.GET, url, null, MediaType.APPLICATION_JSON);
    }

    public Object ensureDefaultOwner() {
        ensureConfigured();
        throw new RenException("默认身份由统一用户管理维护");
    }

    public void cleanupForAccount(Long accountId,String profileId) {
        ensureConfigured();
        HttpHeaders headers=new HttpHeaders();headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setBearerAuth(buildFaceJwt(faceProperties.getJwtSecret(),accountId));
        String url="default".equals(profileId)?base()+"/face/accounts/retire-legacy-default":base()+"/face/profiles/"+profileId;
        exchangeEntity("default".equals(profileId)?HttpMethod.POST:HttpMethod.DELETE,url,new HttpEntity<>(headers));
    }

    public Object getProfile(String userId) {
        ensureConfigured();
        return exchange(HttpMethod.GET, base() + "/face/profiles/" + userId, null,
                MediaType.APPLICATION_JSON);
    }

    public Object createProfile(Map<String, Object> body) {
        ensureConfigured();
        Map<String, Object> safe = sanitizeClientBody(body);
        HttpHeaders headers = authHeaders(MediaType.APPLICATION_JSON);
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(safe, headers);
        return exchangeEntity(HttpMethod.POST, base() + "/face/profiles", entity);
    }

    public Object uploadFace(String userId, MultipartFile image) {
        ensureConfigured();
        try {
            MultiValueMap<String, Object> form = new LinkedMultiValueMap<>();
            ByteArrayResource resource = new ByteArrayResource(image.getBytes()) {
                @Override
                public String getFilename() {
                    return image.getOriginalFilename() != null
                            ? image.getOriginalFilename()
                            : "face.jpg";
                }
            };
            form.add("image", resource);
            HttpHeaders headers = authHeaders(MediaType.MULTIPART_FORM_DATA);
            HttpEntity<MultiValueMap<String, Object>> entity = new HttpEntity<>(form, headers);
            return exchangeEntity(HttpMethod.POST,
                    base() + "/face/profiles/" + userId + "/faces", entity);
        } catch (RenException e) {
            throw e;
        } catch (Exception e) {
            log.warn("face upload proxy failed: {}", e.getMessage());
            throw new RenException("上传人脸失败");
        }
    }

    public Object activate(String userId) {
        ensureConfigured();
        return exchange(HttpMethod.POST, base() + "/face/profiles/" + userId + "/activate",
                null, MediaType.APPLICATION_JSON);
    }

    public Object deleteProfile(String userId) {
        ensureConfigured();
        return exchange(HttpMethod.DELETE, base() + "/face/profiles/" + userId, null,
                MediaType.APPLICATION_JSON);
    }

    /** 设备采集待命名草稿列表（与正式 profiles 分离）。 */
    public Object listEnrollmentSessions() {
        ensureConfigured();
        return exchange(HttpMethod.GET, base() + "/face/enrollment/sessions", null,
                MediaType.APPLICATION_JSON);
    }

    public byte[] enrollmentPreview(String sessionId) {
        ensureConfigured();
        try {
            HttpHeaders headers = authHeaders(MediaType.APPLICATION_JSON);
            headers.setAccept(java.util.Collections.singletonList(MediaType.IMAGE_JPEG));
            HttpEntity<Void> entity = new HttpEntity<>(headers);
            ResponseEntity<byte[]> response = restTemplate.exchange(
                    base() + "/face/enrollment/sessions/" + sessionId + "/preview",
                    HttpMethod.GET, entity, byte[].class);
            return response.getBody() != null ? response.getBody() : new byte[0];
        } catch (HttpStatusCodeException e) {
            String detail = e.getResponseBodyAsString();
            log.warn("[FACE_ENROLL] preview http={} session={}", e.getStatusCode().value(),
                    redactId(sessionId));
            throw new RenException(parseFaceError(detail, e.getStatusCode().value()));
        } catch (RenException e) {
            throw e;
        } catch (Exception e) {
            log.warn("[FACE_ENROLL] preview unreachable");
            throw new RenException("人脸服务不可达");
        }
    }

    public Object confirmEnrollment(String sessionId, Map<String, Object> body) {
        ensureConfigured();
        Map<String, Object> safe = sanitizeClientBody(body);
        HttpHeaders headers = authHeaders(MediaType.APPLICATION_JSON);
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(safe, headers);
        log.info("[FACE_ENROLL] event=confirm_proxy session={}", redactId(sessionId));
        return exchangeEntity(HttpMethod.POST,
                base() + "/face/enrollment/sessions/" + sessionId + "/confirm", entity);
    }

    public Object discardEnrollment(String sessionId) {
        ensureConfigured();
        log.info("[FACE_ENROLL] event=discard_proxy session={}", redactId(sessionId));
        return exchange(HttpMethod.DELETE,
                base() + "/face/enrollment/sessions/" + sessionId + "/discard",
                null, MediaType.APPLICATION_JSON);
    }

    private static String redactId(String value) {
        if (value == null || value.length() < 8) {
            return "***";
        }
        return value.substring(0, 4) + "..." + value.substring(value.length() - 4);
    }

    private String base() {
        return StringUtils.removeEnd(faceProperties.getBaseUrl().trim(), "/");
    }

    private void ensureConfigured() {
        if (StringUtils.isBlank(faceProperties.getBaseUrl())) {
            throw new RenException("人脸服务未配置：请设置 xiaozhi.face.base-url / FACE_API_BASE_URL");
        }
        if (StringUtils.isBlank(faceProperties.getJwtSecret())) {
            // 与 profile 无关：仅显式 allow-insecure 可旁路
            if (!faceProperties.isAllowInsecure()) {
                throw new RenException(
                        "FACE_JWT_SECRET 未配置：已 fail-closed（与 profile 无关），"
                                + "拒绝代理访问人脸服务");
            }
            log.warn(
                    "face proxy running without JWT (allow-insecure=true, profile={})",
                    activeProfile);
        }
    }

    /**
     * 剥离客户端伪造的租户字段；account_id 只来自 SecurityUser。
     */
    public static Map<String, Object> sanitizeClientBody(Map<String, Object> body) {
        if (body == null || body.isEmpty()) {
            return body == null ? Map.of() : body;
        }
        Map<String, Object> copy = new HashMap<>(body);
        copy.remove("account_id");
        copy.remove("accountId");
        copy.remove("FACE_DEFAULT_ACCOUNT");
        return copy;
    }

    private HttpHeaders authHeaders(MediaType contentType) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(contentType);
        String secret = faceProperties.getJwtSecret();
        if (StringUtils.isNotBlank(secret)) {
            headers.setBearerAuth(buildFaceJwt(secret));
        }
        return headers;
    }

    private String buildFaceJwt(String secret) {
        return buildFaceJwt(secret,SecurityUser.getUserId());
    }
    private String buildFaceJwt(String secret,Long uid) {
        long now = System.currentTimeMillis() / 1000;
        Map<String, Object> payload = new HashMap<>();
        payload.put("ver", 1);
        // 租户隔离：仅 SecurityUser.getUserId()；禁止 default/MAC/usr_*
        if (uid == null) {
            throw new RenException("未登录，无法访问人脸服务");
        }
        String accountId = FaceAccountIdRules.normalize(uid);
        if (accountId == null) {
            throw new RenException("非法登录用户身份，无法访问人脸服务");
        }
        payload.put("account_id", accountId);
        payload.put("device_id", "manager-web-" + accountId);
        payload.put("iat", now);
        payload.put("exp", now + 3600);
        return JWTUtil.createToken(payload, secret.getBytes(StandardCharsets.UTF_8));
    }

    private Object exchange(HttpMethod method, String url, Object body, MediaType contentType) {
        HttpHeaders headers = authHeaders(contentType);
        HttpEntity<?> entity = body == null ? new HttpEntity<>(headers) : new HttpEntity<>(body, headers);
        return exchangeEntity(method, url, entity);
    }

    private Object exchangeEntity(HttpMethod method, String url, HttpEntity<?> entity) {
        try {
            ResponseEntity<Object> response = restTemplate.exchange(url, method, entity, Object.class);
            return response.getBody();
        } catch (HttpStatusCodeException e) {
            String detail = e.getResponseBodyAsString();
            log.warn("face-api {} {} -> {} {}", method, url, e.getStatusCode().value(),
                    abbreviate(detail));
            throw new RenException(parseFaceError(detail, e.getStatusCode().value()));
        } catch (RenException e) {
            throw e;
        } catch (Exception e) {
            log.warn("face-api unreachable: {}", e.getMessage());
            throw new RenException("人脸服务不可达");
        }
    }

    private static String abbreviate(String s) {
        if (s == null) {
            return "";
        }
        return s.length() > 200 ? s.substring(0, 200) + "..." : s;
    }

    private static String parseFaceError(String body, int status) {
        if (StringUtils.isBlank(body)) {
            return "人脸服务错误 (" + status + ")";
        }
        // 尝试提取 FastAPI detail.message
        int msgIdx = body.indexOf("\"message\"");
        if (msgIdx >= 0) {
            int start = body.indexOf(':', msgIdx);
            if (start > 0) {
                int q1 = body.indexOf('"', start + 1);
                int q2 = q1 > 0 ? body.indexOf('"', q1 + 1) : -1;
                if (q1 > 0 && q2 > q1) {
                    return body.substring(q1 + 1, q2);
                }
            }
        }
        return "人脸服务错误 (" + status + ")";
    }
}
