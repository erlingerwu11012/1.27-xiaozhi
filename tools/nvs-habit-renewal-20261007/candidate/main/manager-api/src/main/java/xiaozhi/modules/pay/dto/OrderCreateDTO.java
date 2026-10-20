package xiaozhi.modules.pay.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

/**
 * 创建支付订单请求
 */
@Data
@Schema(description = "创建支付订单请求")
public class OrderCreateDTO {

    @NotNull(message = "套餐ID不能为空")
    @Schema(description = "套餐ID", required = true)
    private Long packageId;

    @NotBlank(message = "支付渠道不能为空")
    @Schema(description = "支付渠道：mock/wechat/alipay", required = true)
    private String channel;
}
