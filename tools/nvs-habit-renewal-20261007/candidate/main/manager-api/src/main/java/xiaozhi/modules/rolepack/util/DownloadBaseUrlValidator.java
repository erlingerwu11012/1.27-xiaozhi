package xiaozhi.modules.rolepack.util;

import java.net.URI;
import java.util.Locale;
import java.util.Set;

import org.apache.commons.lang3.StringUtils;

import xiaozhi.common.exception.RenException;

/**
 * 校验 role-pack download-base-url：必须可被固件 TLS/host 白名单接受，禁止占位与不安全形式。
 */
public final class DownloadBaseUrlValidator {

    private static final Set<String> PLACEHOLDER_HOSTS = Set.of(
            "official-host",
            "example.com",
            "example.org",
            "localhost",
            "host.docker.internal");

    /** 当前固件 CONFIG_SPINE_OTA_ALLOWED_HOSTS 已知允许的 host（小写） */
    public static final Set<String> FIRMWARE_ALLOWED_HOSTS = Set.of(
            "cdn.xiaozhi.me",
            "assets.xiaozhi.me",
            "api.realecho.cn");

    private DownloadBaseUrlValidator() {
    }

    /**
     * @return 规范化后的 base（无末尾 /），形如 https://cdn.xiaozhi.me/xiaozhi
     */
    public static String requireValid(String raw) {
        if (StringUtils.isBlank(raw)) {
            throw new RenException(
                    "未配置 xiaozhi.role-pack.download-base-url（请设置环境变量 ROLE_PACK_DOWNLOAD_BASE_URL，例如 https://cdn.xiaozhi.me/xiaozhi）");
        }
        String trimmed = raw.trim();
        if (trimmed.toLowerCase(Locale.ROOT).contains("official-host")
                || trimmed.toLowerCase(Locale.ROOT).contains("placeholder")) {
            throw new RenException("download-base-url 禁止 official-host 等占位主机，请配置真实 HTTPS CDN");
        }
        URI uri;
        try {
            uri = URI.create(trimmed);
        } catch (Exception e) {
            throw new RenException("download-base-url 非法 URI");
        }
        if (uri.getScheme() == null || !"https".equalsIgnoreCase(uri.getScheme())) {
            throw new RenException("download-base-url 必须为 https://");
        }
        if (uri.getUserInfo() != null) {
            throw new RenException("download-base-url 禁止 userinfo");
        }
        if (uri.getFragment() != null) {
            throw new RenException("download-base-url 禁止 fragment");
        }
        if (uri.getRawQuery() != null) {
            throw new RenException("download-base-url 禁止 query");
        }
        if (uri.getPort() != -1) {
            throw new RenException("download-base-url 禁止显式端口（含 :443）");
        }
        String host = uri.getHost();
        if (StringUtils.isBlank(host)) {
            throw new RenException("download-base-url host 不能为空");
        }
        host = host.toLowerCase(Locale.ROOT);
        if (PLACEHOLDER_HOSTS.contains(host) || host.endsWith(".local")) {
            throw new RenException("download-base-url 禁止 localhost / 占位 host: " + host);
        }
        if (RolePackSigner.isIpLiteral(host)) {
            throw new RenException("download-base-url 禁止 IP literal");
        }
        String path = uri.getRawPath();
        if (path == null) {
            path = "";
        }
        while (path.endsWith("/") && path.length() > 1) {
            path = path.substring(0, path.length() - 1);
        }
        if (path.isEmpty()) {
            path = "/xiaozhi";
        } else if (!path.contains("/xiaozhi")) {
            path = path + "/xiaozhi";
        }
        return "https://" + host + path;
    }

    public static boolean isFirmwareAllowlistedHost(String httpsUrlOrBase) {
        try {
            URI u = URI.create(httpsUrlOrBase.trim());
            String host = u.getHost();
            return host != null && FIRMWARE_ALLOWED_HOSTS.contains(host.toLowerCase(Locale.ROOT));
        } catch (Exception e) {
            return false;
        }
    }

    public static String hostOf(String httpsUrl) {
        URI u = URI.create(httpsUrl.trim());
        return u.getHost() == null ? "" : u.getHost().toLowerCase(Locale.ROOT);
    }
}
