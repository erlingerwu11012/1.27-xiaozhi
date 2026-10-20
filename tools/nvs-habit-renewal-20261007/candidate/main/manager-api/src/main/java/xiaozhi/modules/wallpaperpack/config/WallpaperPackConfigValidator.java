package xiaozhi.modules.wallpaperpack.config;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Component;

import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.modules.rolepack.config.RolePackProperties;
import xiaozhi.modules.rolepack.util.DownloadBaseUrlValidator;
import xiaozhi.modules.rolepack.util.RolePackSigner;

@Slf4j
@Component
@RequiredArgsConstructor
public class WallpaperPackConfigValidator {

    private final WallpaperPackProperties wallpaperProperties;
    private final RolePackProperties rolePackProperties;
    private final RolePackSigner signer;

    @PostConstruct
    public void validate() {
        String raw = System.getenv("WALLPAPER_PACK_DOWNLOAD_BASE_URL");
        if (StringUtils.isBlank(raw)) {
            raw = wallpaperProperties.getDownloadBaseUrl();
        }
        if (StringUtils.isBlank(raw)) {
            raw = System.getenv("ROLE_PACK_DOWNLOAD_BASE_URL");
        }
        if (StringUtils.isBlank(raw)) {
            raw = rolePackProperties.getDownloadBaseUrl();
        }
        try {
            String normalized = DownloadBaseUrlValidator.requireValid(raw);
            wallpaperProperties.setDownloadBaseUrl(normalized);
            log.info("WallpaperPack: download-base-url OK -> {}", normalized);
        } catch (Exception e) {
            log.error("WallpaperPack: download-base-url 非法，发布/部署将 fail-closed: {}", e.getMessage());
        }
        if (!signer.isReady()) {
            log.error("WallpaperPack: 签名未就绪（复用 RolePackSigner），发布/部署将 fail-closed");
        }
    }
}
