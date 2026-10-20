package xiaozhi.modules.pay.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * 支付套餐实体
 */
@Data
@EqualsAndHashCode(callSuper = false)
@TableName("pay_package")
@Schema(description = "支付套餐")
public class PayPackageEntity {

    @TableId(type = IdType.AUTO)
    @Schema(description = "主键")
    private Long id;

    @Schema(description = "套餐编码（全局唯一）")
    private String packageCode;

    @Schema(description = "套餐名称")
    private String name;

    @Schema(description = "套餐描述")
    private String description;

    @Schema(description = "价格（分）")
    private Integer amountCents;

    @Schema(description = "发放额度（点）")
    private Long quotaPoints;

    @Schema(description = "是否启用：1=启用，0=禁用")
    private Integer enabled;

    @Schema(description = "排序权重，越小越靠前")
    private Integer sort;

    @Schema(description = "创建时间")
    private Date createdAt;

    @Schema(description = "更新时间")
    private Date updatedAt;
}
