package xiaozhi.modules.device.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.Getter;
import lombok.Setter;

@Data
@Schema(description = "设备OTA检测版本返回体，包含激活码要求")
public class DeviceReportRespDTO {
    @Schema(description = "服务器时间")
    private ServerTime server_time;

    @Schema(description = "激活码")
    private Activation activation;

    @Schema(description = "错误信息")
    private String error;

    @Schema(description = "固件版本信息")
    private Firmware firmware;

    @Schema(description = "WebSocket配置")
    private Websocket websocket;

    @Schema(description = "MQTT Gateway配置")
    private MQTT mqtt;

    @Getter
    @Setter
    public static class Firmware {
        @Schema(description = "版本号")
        private String version;
        @Schema(description = "下载地址")
        private String url;
    }

    public static DeviceReportRespDTO createError(String message) {
        DeviceReportRespDTO resp = new DeviceReportRespDTO();
        resp.setError(message);
        return resp;
    }

    @Setter
    @Getter
    public static class Activation {
        @Schema(description = "用户配对用 6 位激活码（低熵，仅控制台绑定）")
        private String code;

        @Schema(description = "激活码信息: 激活地址")
        private String message;

        @Schema(description = "挑战码（设备标识，非密钥）")
        private String challenge;

        @Schema(description = "高熵 bootstrap 兑换凭证（256-bit）；固件须保存，绑定后用 X-Activation-Code 出示一次")
        private String bootstrap_code;
    }

    @Getter
    @Setter
    public static class ServerTime {
        @Schema(description = "时间戳")
        private Long timestamp;

        @Schema(description = "时区")
        private String timeZone;

        @Schema(description = "时区偏移量，单位为分钟")
        private Integer timezone_offset;
    }

    @Getter
    @Setter
    public static class Websocket {
        @Schema(description = "WebSocket服务器地址")
        private String url;
        @Schema(description = "WebSocket 认证 token")
        private String token;
        @Schema(description = "WebSocket 协议版本")
        private Integer version;
        @Schema(description = "设备级 bootstrap 密钥（仅一次性下发；固件须持久化并在后续 OTA 的 Authorization 中出示）")
        private String auth_key;
    }

    @Getter
    @Setter
    public static class MQTT {
        @Schema(description = "MQTT 配置网址")
        private String endpoint;
        @Schema(description = "MQTT 客户端唯一标识符")
        private String client_id;
        @Schema(description = "MQTT 认证用户名")
        private String username;
        @Schema(description = "MQTT 认证密码")
        private String password;
        @Schema(description = "ESP32 发布消息的主题")
        private String publish_topic;
        @Schema(description = "ESP32 订阅的主题")
        private String subscribe_topic;
    }
}