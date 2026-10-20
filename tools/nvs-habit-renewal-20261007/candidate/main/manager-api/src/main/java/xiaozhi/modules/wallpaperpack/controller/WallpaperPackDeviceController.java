package xiaozhi.modules.wallpaperpack.controller;

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
import xiaozhi.modules.wallpaperpack.dto.WallpaperOtaAckDTO;
import xiaozhi.modules.wallpaperpack.service.WallpaperDeployService;
import xiaozhi.modules.wallpaperpack.util.WallpaperPackConstants;
import xiaozhi.modules.wallpaperpack.vo.WallpaperOtaAckResultVO;

/**
 * 设备/内部通道：短时下载、ACK、pending 重投。
 * 鉴权：download 凭 Redis token（anon）；其余走 Shiro server 过滤器（Bearer server.secret）。
 */
@Tag(name = "壁纸包-设备内部")
@RestController
@RequiredArgsConstructor
public class WallpaperPackDeviceController {

    private final WallpaperDeployService wallpaperDeployService;

    @GetMapping("/wallpaper-packs/download/{token}")
    @Operation(summary = "设备凭短时令牌下载官方角色包")
    public ResponseEntity<byte[]> download(@PathVariable("token") String token) {
        byte[] data = wallpaperDeployService.downloadByToken(token);
        return ResponseEntity.ok()
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .contentLength(data.length)
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        wallpaperDeployService.resolveContentDisposition(token))
                .header(HttpHeaders.CACHE_CONTROL, "no-store")
                .body(data);
    }

    @PostMapping("/wallpaper-packs/device/ack")
    @Operation(summary = "设备 wallpaper_ota_status 回执（服务间密钥 + X-Device-Id）")
    public Result<WallpaperOtaAckResultVO> ack(
            @RequestHeader(value = "X-Device-Id", required = false) String deviceIdHeader,
            @RequestHeader(value = "device-id", required = false) String deviceIdAlt,
            @Valid @RequestBody WallpaperOtaAckDTO ack) {
        String deviceId = StringUtils.isNotBlank(deviceIdHeader) ? deviceIdHeader : deviceIdAlt;
        if (StringUtils.isBlank(deviceId)) {
            throw new RenException("缺少 X-Device-Id");
        }
        WallpaperOtaAckResultVO result = wallpaperDeployService.handleDeviceAck(deviceId, ack);
        return new Result<WallpaperOtaAckResultVO>().ok(result);
    }

    @GetMapping("/wallpaper-packs/device/pending")
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
        Map<String, Object> payload = wallpaperDeployService.buildPendingPushPayload(deviceId, sessionId);
        Map<String, Object> body = new HashMap<>();
        if (payload == null) {
            body.put("hasPending", false);
        } else {
            Object claimedAttemptObj = payload.remove(WallpaperPackConstants.PENDING_CLAIM_ATTEMPT_KEY);
            Object leaseObj = payload.remove(WallpaperPackConstants.PENDING_CLAIM_LEASE_KEY);
            Object versionObj = payload.remove(WallpaperPackConstants.PENDING_CLAIM_VERSION_KEY);
            Object claimedSessionObj = payload.remove(WallpaperPackConstants.PENDING_CLAIM_SESSION_KEY);
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

    @PostMapping("/wallpaper-packs/device/release-pending")
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
        wallpaperDeployService.releasePendingDelivery(deviceId, taskId, deliveryLeaseId, claimedSessionId);
        Map<String, Object> body = new HashMap<>();
        body.put("deviceId", deviceId);
        body.put("taskId", taskId);
        body.put("released", true);
        return new Result<Map<String, Object>>().ok(body);
    }

    @PostMapping("/wallpaper-packs/device/cancel-pending-wallpaper")
    @Operation(summary = "取消指定设备 pending/queued/retrying 的 update_wallpaper 任务（服务间密钥）")
    public Result<Map<String, Object>> cancelPendingWallpaper(
            @RequestParam("deviceId") String deviceId,
            @RequestParam(value = "reason", required = false) String reason) {
        if (StringUtils.isBlank(deviceId)) {
            throw new RenException("缺少 deviceId");
        }
        var cancelled = wallpaperDeployService.cancelPendingUpdateWallpaper(deviceId, reason, null);
        Map<String, Object> body = new HashMap<>();
        body.put("deviceId", deviceId);
        body.put("cancelledCount", cancelled.size());
        body.put("tasks", cancelled);
        return new Result<Map<String, Object>>().ok(body);
    }

    @PostMapping("/wallpaper-packs/device/delivery-aborted")
    @Operation(summary = "设备在 update_wallpaper 后异常断开，停止自动重投（服务间密钥 + X-Device-Id）")
    public Result<xiaozhi.modules.wallpaperpack.vo.WallpaperDeployTaskVO> deliveryAborted(
            @RequestHeader(value = "X-Device-Id", required = false) String deviceIdHeader,
            @RequestHeader(value = "device-id", required = false) String deviceIdAlt,
            @RequestParam(value = "taskId", required = false) String taskId) {
        String deviceId = StringUtils.isNotBlank(deviceIdHeader) ? deviceIdHeader : deviceIdAlt;
        if (StringUtils.isBlank(deviceId)) {
            throw new RenException("缺少 X-Device-Id");
        }
        return new Result<xiaozhi.modules.wallpaperpack.vo.WallpaperDeployTaskVO>()
                .ok(wallpaperDeployService.markAbnormalDisconnectAfterUpdateWallpaper(deviceId, taskId));
    }
}
