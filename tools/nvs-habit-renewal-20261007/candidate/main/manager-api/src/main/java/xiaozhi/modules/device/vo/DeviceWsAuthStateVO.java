package xiaozhi.modules.device.vo;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "设备 WSS 鉴权状态（服务间）")
public class DeviceWsAuthStateVO {

    @Schema(description = "规范化 device_id（12 位 hex）")
    private String deviceId;

    @Schema(description = "凭证版本")
    private Long credentialVersion;

    @Schema(description = "active|unbound|disabled")
    private String status;

    @Schema(description = "v1 iat<=此值则拒绝；null 表示尚未设置 legacy 边界")
    private Long legacyRevokedBeforeIat;

    @Schema(description = "是否已配置 bootstrap 密钥（不返回哈希/明文）")
    private Boolean bootstrapConfigured;

    @Schema(description = "状态更新时间 Unix 秒")
    private Long updatedAtEpochSec;
}
