package xiaozhi.modules.pay.vo;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

/**
 * one-api 设备 token 内部接口返回值（仅服务间使用，严禁落日志）。
 */
@Data
@Schema(description = "one-api 设备 token 内部返回值")
public class OneApiDeviceTokenVO {

    @Schema(description = "one-api 设备 token key（明文，仅服务间传输，勿打印）")
    private String token;

    @Schema(description = "one-api 用户ID")
    private Long oneapiUserId;

    @Schema(description = "token key 的 SHA-256 指纹（hex）")
    private String fingerprint;
}
