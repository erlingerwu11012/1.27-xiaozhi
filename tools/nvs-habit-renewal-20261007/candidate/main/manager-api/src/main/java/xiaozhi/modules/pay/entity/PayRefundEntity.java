package xiaozhi.modules.pay.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * 支付退款单实体（预留，阶段1不启用真实退款）
 */
@Data
@EqualsAndHashCode(callSuper = false)
@TableName("pay_refund")
@Schema(description = "支付退款单")
public class PayRefundEntity {

    @TableId(type = IdType.AUTO)
    @Schema(description = "主键")
    private Long id;

    @Schema(description = "商户退款单号（全局唯一）")
    private String outRefundNo;

    @Schema(description = "原商户订单号")
    private String orderNo;

    @Schema(description = "用户ID")
    private Long userId;

    @Schema(description = "退款金额（分）")
    private Integer amountCents;

    @Schema(description = "退款原因")
    private String reason;

    @Schema(description = "退款渠道：wechat/alipay")
    private String channel;

    @Schema(description = "退款状态：pending/success/failed")
    private String status;

    @Schema(description = "创建时间")
    private Date createdAt;

    @Schema(description = "更新时间")
    private Date updatedAt;
}
