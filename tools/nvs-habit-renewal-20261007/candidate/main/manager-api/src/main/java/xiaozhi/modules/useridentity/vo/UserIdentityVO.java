package xiaozhi.modules.useridentity.vo;

import java.util.List;

import lombok.Data;

@Data
public class UserIdentityVO {
    private String userId;
    private String displayName;
    private String status;
    private List<String> faceProfileIds;
    private List<String> voiceprintIds;
}
