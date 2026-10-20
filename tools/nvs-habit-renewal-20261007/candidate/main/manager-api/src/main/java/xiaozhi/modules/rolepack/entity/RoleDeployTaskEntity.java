package xiaozhi.modules.rolepack.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = false)
@TableName("ai_role_deploy_task")
@Schema(description = "视觉角色部署任务")
public class RoleDeployTaskEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String taskId;
    private String deviceId;
    private Long rolePackId;
    private String packId;
    private Long requestedBy;
    private String state;
    private Integer progress;
    private String errorCode;
    private String errorMessage;
    private Integer retryCount;
    /** update_spine 实际投递次数（含首次推送与重连重投） */
    private Integer attemptCount;
    /** 本次领取不可复用 lease（UUID）；release 成功后清空；绝不复用 */
    private String deliveryLeaseId;
    /** 单调递增领取版本；release 不回退；永不复用 */
    private Long deliveryVersion;
    /** 领取时的 WebSocket session_id（可选，用于精确释放） */
    private String claimedSessionId;
    private String downloadToken;
    private String signature;
    private String payloadJson;
    private String currentRoleVersion;
    private Date lastDeliveredAt;
    private Date acceptedAt;
    private Date nextAttemptAt;
    private Date completedAt;
    private Date cancelledAt;
    private String cancelReason;
    private String lastError;
    private Date createdAt;
    private Date updatedAt;
}
