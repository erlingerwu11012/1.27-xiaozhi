package xiaozhi.modules.rolepack.vo;

import java.util.List;

import lombok.Data;

@Data
public class RolePackInspectVO {
    private String packId;
    private String version;
    private String format;
    private String spineRuntimeVersion;
    private String skel;
    private String atlas;
    private String png;
    private Long size;
    private String defaultMinFw;
    private List<String> defaultSupportedBoards;
}
