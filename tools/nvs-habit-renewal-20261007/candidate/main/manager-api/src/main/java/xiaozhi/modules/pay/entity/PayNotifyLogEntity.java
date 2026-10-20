package xiaozhi.modules.pay.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * 支付回调日志实体
 */
@Data
@EqualsAndHashCode(callSuper = false)
@TableName("pay_notify_log")
@Schema(description = "支付回调日志")
public class PayNotifyLogEntity {

    @TableId(type = IdType.AUTO)
    @Schema(description = "主键")
    private Long id;

    @Schema(description = "关联订单号")
    private String orderNo;

    @Schema(description = "支付渠道：mock/wechat/alipay")
    private String channel;

    @Schema(description = "通知类型：支付/退款/关闭等")
    private String notifyType;

    @Schema(description = "回调原始报文（脱敏后存储）")
    private String rawBody;

    @Schema(description = "处理状态：success/failed/ignored")
    private String status;

    @Schema(description = "处理失败原因")
    private String errorMsg;

    @Schema(description = "创建时间")
    private Date createdAt;

    @Schema(description = "更新时间")
    private Date updatedAt;
}
