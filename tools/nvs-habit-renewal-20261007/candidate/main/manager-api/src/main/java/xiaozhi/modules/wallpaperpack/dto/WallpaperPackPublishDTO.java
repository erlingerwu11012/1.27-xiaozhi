package xiaozhi.modules.wallpaperpack.dto;

import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
@Schema(description = "发布官方视觉角色包。packId/version/minFw/boards 若传入仅作一致性核对或被忽略，不作为权威来源")
public class WallpaperPackPublishDTO {

    @Schema(description = "客户端可选传入；必须与包内 role_id 一致，否则拒绝。权威来源是 spine.bin")
    private String packId;

    @NotBlank
    private String displayName;

    private String description;

    @Schema(description = "客户端可选传入；必须与包内 version 一致，否则拒绝")
    private String version;

    @Schema(description = "客户端传入将被忽略，使用服务端 xiaozhi.role-pack.default-min-fw")
    private String minFw;

    @Schema(description = "客户端传入将被忽略，使用服务端 default-supported-boards")
    private List<String> boardModelAllowlist;

    @Schema(description = "已废弃：客户端 previewUrl 不再信任")
    private String previewUrl;

    @Schema(description = "是否直接发布为 published；默认 true")
    private Boolean publishNow = true;
}
