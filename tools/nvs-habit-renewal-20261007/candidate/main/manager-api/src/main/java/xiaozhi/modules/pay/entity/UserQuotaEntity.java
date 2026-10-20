package xiaozhi.modules.pay.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * 用户额度实体
 */
@Data
@EqualsAndHashCode(callSuper = false)
@TableName("user_quota")
@Schema(description = "用户额度")
public class UserQuotaEntity {

    @TableId(type = IdType.AUTO)
    @Schema(description = "主键")
    private Long id;

    @Schema(description = "用户ID")
    private Long userId;

    @Schema(description = "当前余额（点）")
    private Long balance;

    @Schema(description = "累计充值额度（点）")
    private Long totalRecharge;

    @Schema(description = "累计消费额度（点）")
    private Long totalConsume;

    @Schema(description = "创建时间")
    private Date createdAt;

    @Schema(description = "更新时间")
    private Date updatedAt;
}
