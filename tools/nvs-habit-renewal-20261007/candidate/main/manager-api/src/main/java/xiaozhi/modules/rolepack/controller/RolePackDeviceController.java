package xiaozhi.modules.rolepack.controller;

import java.util.HashMap;
import java.util.Map;

import org.apache.commons.lang3.StringUtils;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.rolepack.dto.SpineOtaAckDTO;
import xiaozhi.modules.rolepack.service.RoleDeployService;
import xiaozhi.modules.rolepack.util.RolePackConstants;
import xiaozhi.modules.rolepack.vo.SpineOtaAckResultVO;

/**
 * 设备/内部通道：短时下载、ACK、pending 重投。
 * 鉴权：download 凭 Redis token（anon）；其余走 Shiro server 过滤器（Bearer server.secret）。
 */
@Tag(name = "视觉角色包-设备内部")
@RestController
@RequiredArgsConstructor
public class RolePackDeviceController {

    private final RoleDeployService roleDeployService;

    @GetMapping("/role-packs/download/{token}")
    @Operation(summary = "设备凭短时令牌下载官方角色包")
    public ResponseEntity<byte[]> download(@PathVariable("token") String token) {
        byte[] data = roleDeployService.downloadByToken(token);
        return ResponseEntity.ok()
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .contentLength(data.length)
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        roleDeployService.resolveContentDisposition(token))
                .header(HttpHeaders.CACHE_CONTROL, "no-store")
                .body(data);
    }

    @PostMapping("/role-packs/device/ack")
    @Operation(summary = "设备 spine_ota_status 回执（服务间密钥 + X-Device-Id）")
    public Result<SpineOtaAckResultVO> ack(
            @RequestHeader(value = "X-Device-Id", required = false) String deviceIdHeader,
            @RequestHeader(value = "device-id", required = false) String deviceIdAlt,
            @Valid @RequestBody SpineOtaAckDTO ack) {
        String deviceId = StringUtils.isNotBlank(deviceIdHeader) ? deviceIdHeader : deviceIdAlt;
        if (StringUtils.isBlank(deviceId)) {
            throw new RenException("缺少 X-Device-Id");
        }
        SpineOtaAckResultVO result = roleDeployService.handleDeviceAck(deviceId, ack);
        return new Result<SpineOtaAckResultVO>().ok(result);
    }

    @GetMapping("/role-packs/device/pending")
    @Operation(summary = "查询设备待重投的角色任务载荷")
    public Result<Map<String, Object>> pending(
            @RequestHeader(value = "X-Device-Id", required = false) String deviceIdHeader,
            @RequestParam(value = "deviceId", required = false) String deviceIdParam,
            @RequestHeader(value = "X-Session-Id", required = false) String sessionIdHeader,
            @RequestParam(value = "sessionId", required = false) String sessionIdParam) {
        String deviceId = StringUtils.isNotBlank(deviceIdHeader) ? deviceIdHeader : deviceIdParam;
        if (StringUtils.isBlank(deviceId)) {
            throw new RenException("缺少 deviceId");
        }
        String sessionId = StringUtils.isNotBlank(sessionIdHeader) ? sessionIdHeader : sessionIdParam;
        Map<String, Object> payload = roleDeployService.buildPendingPushPayload(deviceId, sessionId);
        Map<String, Object> body = new HashMap<>();
        if (payload == null) {
            body.put("hasPending", false);
        } else {
            Object claimedAttemptObj = payload.remove(RolePackConstants.PENDING_CLAIM_ATTEMPT_KEY);
            Object leaseObj = payload.remove(RolePackConstants.PENDING_CLAIM_LEASE_KEY);
            Object versionObj = payload.remove(RolePackConstants.PENDING_CLAIM_VERSION_KEY);
            Object claimedSessionObj = payload.remove(RolePackConstants.PENDING_CLAIM_SESSION_KEY);
            int claimedAttempt = claimedAttemptObj instanceof Number n ? n.intValue() : 0;
            long deliveryVersion = versionObj instanceof Number n ? n.longValue() : 0L;
            body.put("hasPending", true);
            body.put("payload", payload);
            body.put("taskId", payload.get("task_id"));
            body.put("attemptCount", claimedAttempt);
            body.put("deliveryLeaseId", leaseObj);
            body.put("deliveryVersion", deliveryVersion);
            if (claimedSessionObj != null) {
                body.put("claimedSessionId", claimedSessionObj);
            }
        }
        return new Result<Map<String, Object>>().ok(body);
    }

    @PostMapping("/role-packs/device/release-pending")
    @Operation(summary = "xiaozhi-server 在领取后发送前发现连接 stale 时释放领取（服务间密钥 + X-Device-Id）")
    public Result<Map<String, Object>> releasePending(
            @RequestHeader(value = "X-Device-Id", required = false) String deviceIdHeader,
            @RequestHeader(value = "device-id", required = false) String deviceIdAlt,
            @RequestParam(value = "taskId", required = false) String taskId,
            @RequestParam(value = "deliveryLeaseId", required = false) String deliveryLeaseId,
            @RequestParam(value = "claimedSessionId", required = false) String claimedSessionId) {
        String deviceId = StringUtils.isNotBlank(deviceIdHeader) ? deviceIdHeader : deviceIdAlt;
        if (StringUtils.isBlank(deviceId)) {
            throw new RenException("缺少 X-Device-Id");
        }
        roleDeployService.releasePendingDelivery(deviceId, taskId, deliveryLeaseId, claimedSessionId);
        Map<String, Object> body = new HashMap<>();
        body.put("deviceId", deviceId);
        body.put("taskId", taskId);
        body.put("released", true);
        return new Result<Map<String, Object>>().ok(body);
    }

    @PostMapping("/role-packs/device/cancel-pending-spine")
    @Operation(summary = "取消指定设备 pending/queued/retrying 的 update_spine 任务（服务间密钥）")
    public Result<Map<String, Object>> cancelPendingSpine(
            @RequestParam("deviceId") String deviceId,
            @RequestParam(value = "reason", required = false) String reason) {
        if (StringUtils.isBlank(deviceId)) {
            throw new RenException("缺少 deviceId");
        }
        var cancelled = roleDeployService.cancelPendingUpdateSpine(deviceId, reason, null);
        Map<String, Object> body = new HashMap<>();
        body.put("deviceId", deviceId);
        body.put("cancelledCount", cancelled.size());
        body.put("tasks", cancelled);
        return new Result<Map<String, Object>>().ok(body);
    }

    @PostMapping("/role-packs/device/delivery-aborted")
    @Operation(summary = "设备在 update_spine 后异常断开，停止自动重投（服务间密钥 + X-Device-Id）")
    public Result<xiaozhi.modules.rolepack.vo.RoleDeployTaskVO> deliveryAborted(
            @RequestHeader(value = "X-Device-Id", required = false) String deviceIdHeader,
            @RequestHeader(value = "device-id", required = false) String deviceIdAlt,
            @RequestParam(value = "taskId", required = false) String taskId) {
        String deviceId = StringUtils.isNotBlank(deviceIdHeader) ? deviceIdHeader : deviceIdAlt;
        if (StringUtils.isBlank(deviceId)) {
            throw new RenException("缺少 X-Device-Id");
        }
        return new Result<xiaozhi.modules.rolepack.vo.RoleDeployTaskVO>()
                .ok(roleDeployService.markAbnormalDisconnectAfterUpdateSpine(deviceId, taskId));
    }
}
