package xiaozhi.modules.pay.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * one-api 充值流水实体
 */
@Data
@EqualsAndHashCode(callSuper = false)
@TableName("oneapi_recharge_log")
@Schema(description = "one-api充值流水")
public class OneapiRechargeLogEntity {

    @TableId(type = IdType.AUTO)
    @Schema(description = "主键")
    private Long id;

    @Schema(description = "订单号")
    private String orderNo;

    @Schema(description = "主系统用户ID")
    private Long sysUserId;

    @Schema(description = "one-api用户ID")
    private Long oneapiUserId;

    @Schema(description = "充值点数")
    private Long points;

    @Schema(description = "实际充入one-api quota")
    private Long oneapiQuota;

    @Schema(description = "充值状态：success/failed")
    private String status;

    @Schema(description = "失败原因")
    private String errorMsg;

    @Schema(description = "创建时间")
    private Date createdAt;

    @Schema(description = "更新时间")
    private Date updatedAt;
}
