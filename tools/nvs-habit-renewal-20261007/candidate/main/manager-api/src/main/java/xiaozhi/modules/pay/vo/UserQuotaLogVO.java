package xiaozhi.modules.pay.vo;

import java.util.Date;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

/**
 * 用户额度流水 VO
 */
@Data
@Schema(description = "用户额度流水")
public class UserQuotaLogVO {

    @Schema(description = "流水ID")
    private Long id;

    @Schema(description = "关联订单号")
    private String orderNo;

    @Schema(description = "变更类型：recharge/consume/refund")
    private String changeType;

    @Schema(description = "变更点数（正为增加，负为扣减）")
    private Long changeAmount;

    @Schema(description = "变更后余额（点）")
    private Long balanceAfter;

    @Schema(description = "备注")
    private String remark;

    @Schema(description = "创建时间")
    private Date createdAt;
}
