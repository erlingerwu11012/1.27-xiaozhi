package xiaozhi.modules.wallpaperpack.vo;

import java.util.List;

import lombok.Data;

@Data
public class WallpaperPackCatalogItemVO {
    private String packId;
    private String displayName;
    private String description;
    private String version;
    private Long size;
    private String minFw;
    private List<String> boardModelAllowlist;
    private String previewUrl;
    private String previewImageUrl;
    private String previewVideoUrl;
    private String status;
}
