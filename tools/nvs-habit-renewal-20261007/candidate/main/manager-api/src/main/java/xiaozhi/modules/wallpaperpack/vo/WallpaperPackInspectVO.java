package xiaozhi.modules.wallpaperpack.vo;

import java.util.List;

import lombok.Data;

@Data
public class WallpaperPackInspectVO {
    private String packId;
    private String version;
    private Integer format;
    private String defaultId;
    private Integer itemCount;
    private Long size;
    private String defaultMinFw;
    private List<String> defaultSupportedBoards;
}
