package xiaozhi.modules.rolepack.config;

import org.springframework.stereotype.Component;

import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.modules.rolepack.util.DownloadBaseUrlValidator;
import xiaozhi.modules.rolepack.util.RolePackSigner;

/**
 * 启动时校验 download-base-url 与签名密钥配对状态；非法配置记 ERROR（发布/部署仍 fail-closed）。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class RolePackConfigValidator {

    private final RolePackProperties properties;
    private final RolePackSigner signer;

    @PostConstruct
    public void validate() {
        String raw = System.getenv("ROLE_PACK_DOWNLOAD_BASE_URL");
        if (raw == null || raw.isBlank()) {
            raw = properties.getDownloadBaseUrl();
        }
        try {
            String normalized = DownloadBaseUrlValidator.requireValid(raw);
            properties.setDownloadBaseUrl(normalized);
            if (!DownloadBaseUrlValidator.isFirmwareAllowlistedHost(normalized)) {
                log.error(
                        "RolePack: download-base-url host={} 不在当前固件白名单 {} 内；设备会拒绝下载。"
                                + "联调请改用 cdn.xiaozhi.me/assets.xiaozhi.me，或同步更新固件 CONFIG_SPINE_OTA_ALLOWED_HOSTS 并重新烧录。",
                        DownloadBaseUrlValidator.hostOf(normalized),
                        DownloadBaseUrlValidator.FIRMWARE_ALLOWED_HOSTS);
            } else {
                log.info("RolePack: download-base-url OK -> {}", normalized);
            }
        } catch (Exception e) {
            log.error("RolePack: download-base-url 非法，发布/部署将 fail-closed: {}", e.getMessage());
        }
        if (!signer.isReady()) {
            log.error("RolePack: 签名未就绪（缺私钥或公钥指纹不匹配），发布/部署将 fail-closed");
        }
    }
}
