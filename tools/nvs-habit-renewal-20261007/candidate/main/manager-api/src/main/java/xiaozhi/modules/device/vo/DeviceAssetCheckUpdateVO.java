package xiaozhi.modules.device.vo;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

import java.util.List;

@Data
@Schema(description = "设备资源待更新查询结果（供 Python 后端轮询）")
public class DeviceAssetCheckUpdateVO {

    @Schema(description = "设备ID")
    private String deviceId;

    @Schema(description = "是否有待更新资源（服务端版本 > 设备当前版本时为 true）")
    private Boolean hasUpdate;

    @Schema(description = "最新资源列表（按 file_type 各一条最新）")
    private List<AssetItemVO> assets;

    @Data
    @Schema(description = "单条资源项")
    public static class AssetItemVO {
        @Schema(description = "类型：emoji / wallpaper")
        private String fileType;
        @Schema(description = "文件访问路径")
        private String fileUrl;
        @Schema(description = "版本号")
        private Integer version;
    }
}
