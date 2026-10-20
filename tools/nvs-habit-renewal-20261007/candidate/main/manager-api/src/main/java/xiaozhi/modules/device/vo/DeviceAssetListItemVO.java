package xiaozhi.modules.device.vo;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "设备资源列表项（供前端展示）")
public class DeviceAssetListItemVO {

    @Schema(description = "记录ID")
    private Long id;

    @Schema(description = "文件访问路径")
    private String fileUrl;

    @Schema(description = "类型：emoji / wallpaper")
    private String fileType;

    @Schema(description = "版本号")
    private Integer version;
}
