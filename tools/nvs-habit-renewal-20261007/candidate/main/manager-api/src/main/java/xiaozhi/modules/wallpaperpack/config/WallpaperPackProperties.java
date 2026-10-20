package xiaozhi.modules.wallpaperpack.config;

import java.util.ArrayList;
import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import lombok.Data;

@Data
@Component
@ConfigurationProperties(prefix = "xiaozhi.wallpaper-pack")
public class WallpaperPackProperties {

    private String storageDir = "wallpaperpacks";

    /** 支持 update_wallpaper 的最低固件版本 */
    private String defaultMinFw = "1.0.0";

    private List<String> defaultSupportedBoards = new ArrayList<>(List.of("esp-box-3"));

    /** 复用角色 OTA 同一 HTTPS host；空则回退 ROLE_PACK_DOWNLOAD_BASE_URL */
    private String downloadBaseUrl = "";

    private String signingPrivateKeyPem = "";
    private String signingPrivateKeyPath = "";
    private String expectedPublicKeySha256 = "";

    private long downloadTokenTtlSeconds = 900;
    private int downloadMaxCount = 10;
    private String pushUrl = "http://127.0.0.1:8006/api/v1/device/send";
    private int taskTimeoutMinutes = 60;
    private int maxRetryCount = 3;
    private int maxRedeliverAttempts = 3;
    private long redeliverBackoffBaseMs = 30_000L;
    private long progressWriteMinIntervalMs = 1000;
    private int progressWriteMinDeltaPercent = 5;
}
