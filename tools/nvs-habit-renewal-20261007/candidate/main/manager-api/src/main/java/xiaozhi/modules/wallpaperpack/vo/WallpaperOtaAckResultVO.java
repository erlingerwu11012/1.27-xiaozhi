package xiaozhi.modules.wallpaperpack.vo;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

/**
 * wallpaper_ota_status 回执处理结果。
 * xiaozhi-server 依据 completed 标志决定是否向设备下发 wallpaper_ota_ack。
 */
@Data
@Schema(description = "wallpaper_ota_status 回执处理结果")
public class WallpaperOtaAckResultVO {

    @Schema(description = "任务ID")
    private String taskId;

    @Schema(description = "设备ID")
    private String deviceId;

    @Schema(description = "中央最新状态")
    private String state;

    @Schema(description = "是否已 completed（成功 ACK 才下发 wallpaper_ota_ack）")
    private boolean completed;

    @Schema(description = "是否为重复 success 上报（幂等命中）")
    private boolean duplicate;

    @Schema(description = "当前投递次数")
    private Integer attemptCount;
}
