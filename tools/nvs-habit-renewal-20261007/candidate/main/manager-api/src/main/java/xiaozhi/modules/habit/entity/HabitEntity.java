package xiaozhi.modules.habit.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * 手动习惯管理实体
 */
@Data
@EqualsAndHashCode(callSuper = false)
@TableName("sys_habits")
@Schema(description = "手动习惯")
public class HabitEntity {

    @TableId(type = IdType.AUTO)
    @Schema(description = "主键")
    private Integer id;

    @Schema(description = "英文意图标签，如 drink_water")
    private String intent;

    @Schema(description = "中文描述，如 喝水")
    private String description;

    @Schema(description = "触发小时 0-23")
    private Integer hour;

    @Schema(description = "触发分钟 0-59")
    private Integer minute;

    @Schema(description = "提前提醒分钟数，默认2")
    private Integer advanceMinutes;

    @Schema(description = "来源：manual=手动创建，auto=系统自动提取")
    private String source;

    @Schema(description = "是否启用：1=启用，0=禁用")
    private Integer enabled;

    @Schema(description = "是否已同步到设备端：0=待同步，1=已同步")
    private Integer synced;

    @Schema(description = "目标设备ID，NULL 表示广播到所有设备")
    private String deviceId;

    @Schema(description = "所属用户ID")
    private Long userId;
    private String recipientPersonId;
    private String recipientDisplayName;
    private String syncState;
    private String syncError;
    private String contentHash;
    private Integer deviceRuleId;
    private Long configVersion;
    private Date syncedAt;

    @Schema(description = "创建时间")
    private Date createdAt;

    @Schema(description = "更新时间")
    private Date updatedAt;
}
