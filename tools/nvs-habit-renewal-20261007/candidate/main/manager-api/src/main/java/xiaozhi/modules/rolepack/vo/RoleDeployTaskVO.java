package xiaozhi.modules.rolepack.vo;

import java.util.Date;

import lombok.Data;

@Data
public class RoleDeployTaskVO {
    private String taskId;
    private String deviceId;
    private String packId;
    private String displayName;
    private String version;
    private String state;
    private Integer progress;
    private String errorCode;
    private String errorMessage;
    private Integer retryCount;
    private Integer attemptCount;
    private Date createdAt;
    private Date updatedAt;
    private Date completedAt;
    private Date cancelledAt;
    private String cancelReason;
    private String lastError;
    private String currentRoleVersion;
}
