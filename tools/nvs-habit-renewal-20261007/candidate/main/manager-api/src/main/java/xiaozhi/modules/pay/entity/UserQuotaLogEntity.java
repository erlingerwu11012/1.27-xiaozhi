package xiaozhi.modules.pay.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * 用户额度流水实体
 */
@Data
@EqualsAndHashCode(callSuper = false)
@TableName("user_quota_log")
@Schema(description = "用户额度流水")
public class UserQuotaLogEntity {

    @TableId(type = IdType.AUTO)
    @Schema(description = "主键")
    private Long id;

    @Schema(description = "用户ID")
    private Long userId;

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

    @Schema(description = "更新时间")
    private Date updatedAt;
}
