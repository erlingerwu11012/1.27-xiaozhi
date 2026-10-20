package xiaozhi.modules.rolepack.service;

import java.util.List;
import java.util.Map;

import xiaozhi.modules.rolepack.dto.SpineOtaAckDTO;
import xiaozhi.modules.rolepack.vo.RoleDeployTaskVO;
import xiaozhi.modules.rolepack.vo.SpineOtaAckResultVO;

public interface RoleDeployService {

    RoleDeployTaskVO deploy(Long userId, String packId, String deviceId);

    RoleDeployTaskVO getTaskForUser(Long userId, String taskId);

    RoleDeployTaskVO getTaskInternal(String taskId);

    SpineOtaAckResultVO handleDeviceAck(String authenticatedDeviceId, SpineOtaAckDTO ack);

    /**
     * 设备重连时取进行中任务并生成可推送 payload。
     * 受投递次数上限与指数退避约束；超限或不可投递时返回 null。
     * claimedSessionId 为 xiaozhi-server 当前连接 session_id（可空）。
     */
    Map<String, Object> buildPendingPushPayload(String deviceId, String claimedSessionId);

    /**
     * xiaozhi-server 在「领取后、实际发送前」发现连接已 stale 时释放本次领取。
     * 条件更新必须匹配不可复用的 delivery_lease_id（及可选 claimed_session_id）：
     * 旧 release 重放绝不能影响新 session 的 claim；delivery_version 永不回退。
     */
    void releasePendingDelivery(String deviceId, String taskId, String deliveryLeaseId,
            String claimedSessionId);

    /**
     * 取消指定设备上 pending/queued/retrying（及等价 sent）的 update_spine 任务。
     * 仅改状态为 cancelled，不删除历史；不影响其他设备与其他命令。
     *
     * @return 被取消的任务摘要列表
     */
    List<RoleDeployTaskVO> cancelPendingUpdateSpine(String deviceId, String reason, Long actorUserId);

    /**
     * 设备在收到 update_spine 后异常断开：停止自动重投并标记 needs_manual_review。
     */
    RoleDeployTaskVO markAbnormalDisconnectAfterUpdateSpine(String deviceId, String taskId);

    byte[] downloadByToken(String token);

    String resolveContentDisposition(String token);
}
