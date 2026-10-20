package xiaozhi.modules.wallpaperpack.dto;

import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "更新角色包元数据（不含文件替换）")
public class WallpaperPackUpdateDTO {
    private String displayName;
    private String description;
    private String previewUrl;
    private String minFw;
    private List<String> boardModelAllowlist;
    private String status;
}
