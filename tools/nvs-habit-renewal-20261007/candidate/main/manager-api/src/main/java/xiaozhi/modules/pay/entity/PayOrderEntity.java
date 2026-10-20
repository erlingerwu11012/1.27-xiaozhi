package xiaozhi.modules.pay.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * 支付订单实体
 */
@Data
@EqualsAndHashCode(callSuper = false)
@TableName("pay_order")
@Schema(description = "支付订单")
public class PayOrderEntity {

    @TableId(type = IdType.AUTO)
    @Schema(description = "主键")
    private Long id;

    @Schema(description = "商户订单号（全局唯一）")
    private String outTradeNo;

    @Schema(description = "下单用户ID")
    private Long userId;

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

    @Schema(description = "第三方交易号（mock 渠道为 MOCK_订单号）")
    private String tradeNo;

    @Schema(description = "支付成功时间")
    private Date paidAt;

    @Schema(description = "额度发放时间")
    private Date deliveredAt;

    @Schema(description = "充值目标one-api用户ID")
    private Long oneapiUserId;

    @Schema(description = "one-api充值状态：pending/success/failed")
    private String oneapiRechargeStatus;

    @Schema(description = "one-api充值成功时间")
    private Date oneapiRechargeAt;

    @Schema(description = "one-api充值失败原因")
    private String oneapiRechargeMsg;

    @Schema(description = "实际充入one-api quota")
    private Long oneapiRechargeQuota;

    @Schema(description = "充值后one-api余额快照")
    private Long oneapiBalanceAfter;

    @Schema(description = "订单过期时间（预留，可空）")
    private Date expireAt;

    @Schema(description = "创建时间")
    private Date createdAt;

    @Schema(description = "更新时间")
    private Date updatedAt;
}
