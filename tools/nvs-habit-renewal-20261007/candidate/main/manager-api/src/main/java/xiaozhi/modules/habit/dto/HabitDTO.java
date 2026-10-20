package xiaozhi.modules.habit.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

/**
 * 创建/更新手动习惯 DTO
 */
@Data
@Schema(description = "手动习惯请求")
public class HabitDTO {

    @NotBlank(message = "习惯描述不能为空")
    @Schema(description = "中文描述，如 喝水、冥想", required = true)
    private String description;

    @NotNull(message = "触发小时不能为空")
    @Min(value = 0, message = "hour 必须在 0-23 之间")
    @Max(value = 23, message = "hour 必须在 0-23 之间")
    @Schema(description = "每天触发小时 0-23", required = true)
    private Integer hour;

    @Min(value = 0, message = "minute 必须在 0-59 之间")
    @Max(value = 59, message = "minute 必须在 0-59 之间")
    @Schema(description = "每天触发分钟 0-59，默认0")
    private Integer minute = 0;

    @Min(value = 0, message = "提前分钟数不能为负")
    @Schema(description = "提前提醒分钟数，默认2")
    @Max(30)
    private Integer advanceMinutes = 2;

    @Schema(description = "英文意图标签（可选，不填则自动生成）")
    private String intent;

    @Schema(description = "当前账号所属设备MAC（必填）")
    @NotBlank
    private String deviceId;
    @NotBlank
    private String recipientPersonId;
}
