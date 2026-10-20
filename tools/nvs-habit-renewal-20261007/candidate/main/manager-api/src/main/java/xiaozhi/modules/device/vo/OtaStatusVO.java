package xiaozhi.modules.device.vo;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * GET /ota/ 及 POST /ota/（无设备上下文）接口返回体
 * 返回 WebSocket 配置，供设备使用 WebSocket 连接
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@Schema(description = "OTA 状态及 WebSocket、固件连接信息")
public class OtaStatusVO {

    @Schema(description = "状态描述")
    private String message;

    @Schema(description = "服务器时间，固件用于同步")
    private ServerTime server_time;

    @Schema(description = "WebSocket 连接配置")
    private WebsocketConfig websocket;

    @Schema(description = "固件信息")
    private FirmwareConfig firmware;

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Schema(description = "服务器时间")
    public static class ServerTime {
        @Schema(description = "时间戳(毫秒)")
        private Long timestamp;
        @Schema(description = "时区")
        private String timeZone;
        @Schema(description = "时区偏移(分钟)")
        private Integer timezone_offset;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Schema(description = "WebSocket 连接配置")
    public static class WebsocketConfig {
        @Schema(description = "WebSocket 服务器地址，格式 ws://host:port/path")
        private String url;
        @Schema(description = "WebSocket 认证 token，无认证可留空")
        private String token;
        @Schema(description = "WebSocket 协议版本，推荐 2")
        private Integer version;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Schema(description = "固件信息")
    public static class FirmwareConfig {
        @Schema(description = "固件版本号")
        private String version;

        @Schema(description = "固件下载地址（格式：{otaBase}/otaMag/download/{uuid}）")
        private String url;
    }
}
