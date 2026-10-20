package xiaozhi.modules.pay.vo;

import java.util.Date;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

/**
 * 支付订单 VO
 */
@Data
@Schema(description = "支付订单")
public class PayOrderVO {

    @Schema(description = "订单ID")
    private Long id;

    @Schema(description = "商户订单号")
    private String outTradeNo;

    @Schema(description = "套餐ID")
    private Long packageId;

    @Schema(description = "套餐编码快照")
    private String packageCode;

    @Schema(description = "套餐名称快照")
    private String packageName;

    @Schema(description = "订单金额快照（分）")
    private Integer amountCents;

    @Schema(description = "订单额度快照（点）")
    private Long quotaPoints;

    @Schema(description = "支付渠道：mock/wechat/alipay")
    private String channel;

    @Schema(description = "订单状态：pending/paid/delivered/closed/refunded/failed")
    private String status;

    @Schema(description = "第三方交易号")
    private String tradeNo;

    @Schema(description = "创建时间")
    private Date createdAt;

    @Schema(description = "支付成功时间")
    private Date paidAt;

    @Schema(description = "额度发放时间")
    private Date deliveredAt;

    @Schema(description = "one-api充值状态：pending/success/failed")
    private String oneapiRechargeStatus;

    @Schema(description = "实际充入one-api quota")
    private Long oneapiRechargeQuota;

    @Schema(description = "支付宝支付表单 HTML（仅 alipay 渠道创建订单时返回，前端渲染后自动跳转）")
    private String payForm;
}
