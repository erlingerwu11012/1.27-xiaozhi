package xiaozhi.modules.device.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "设备资源上传结果")
public class DeviceAssetUploadDTO {

    @Schema(description = "文件访问路径（相对 uploads/ 或可访问 URL）")
    private String fileUrl;

    @Schema(description = "资源版本号")
    private Integer version;

    @Schema(description = "类型：emoji / wallpaper")
    private String fileType;

    @Schema(description = "设备ID")
    private String deviceId;
}
