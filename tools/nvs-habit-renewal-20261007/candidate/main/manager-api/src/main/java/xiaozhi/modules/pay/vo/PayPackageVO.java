package xiaozhi.modules.pay.vo;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

/**
 * 支付套餐 VO
 */
@Data
@Schema(description = "支付套餐")
public class PayPackageVO {

    @Schema(description = "套餐ID")
    private Long id;

    @Schema(description = "套餐编码")
    private String packageCode;

    @Schema(description = "套餐名称")
    private String name;

    @Schema(description = "套餐描述")
    private String description;

    @Schema(description = "价格（分）")
    private Integer amountCents;

    @Schema(description = "发放额度（点）")
    private Long quotaPoints;
}
