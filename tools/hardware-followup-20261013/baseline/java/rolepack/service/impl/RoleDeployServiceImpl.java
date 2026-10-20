package xiaozhi.modules.rolepack.service.impl;

import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.apache.commons.lang3.StringUtils;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.redis.RedisUtils;
import xiaozhi.modules.device.entity.DeviceEntity;
import xiaozhi.modules.device.service.DeviceService;
import xiaozhi.modules.rolepack.config.RolePackProperties;
import xiaozhi.modules.rolepack.dao.DeviceVisualRoleDao;
import xiaozhi.modules.rolepack.dao.RoleDeployTaskDao;
import xiaozhi.modules.rolepack.dao.RolePackDao;
import xiaozhi.modules.rolepack.dto.SpineOtaAckDTO;
import xiaozhi.modules.rolepack.entity.DeviceVisualRoleEntity;
import xiaozhi.modules.rolepack.entity.RoleDeployTaskEntity;
import xiaozhi.modules.rolepack.entity.RolePackEntity;
import xiaozhi.modules.rolepack.service.RoleDeployService;
import xiaozhi.modules.rolepack.service.RolePackAuditService;
import xiaozhi.modules.rolepack.service.RolePackService;
import xiaozhi.modules.rolepack.util.DownloadBaseUrlValidator;
import xiaozhi.modules.rolepack.util.RoleDeployStateMachine;
import xiaozhi.modules.rolepack.util.RolePackConstants;
import xiaozhi.modules.rolepack.util.RolePackSigner;
import xiaozhi.modules.rolepack.util.SpineRedeliveryPolicy;
import xiaozhi.modules.rolepack.util.VersionCompareUtil;
import xiaozhi.modules.rolepack.vo.RoleDeployTaskVO;
import xiaozhi.modules.rolepack.vo.SpineOtaAckResultVO;
import xiaozhi.modules.sys.service.SysParamsService;
import xiaozhi.modules.visualota.util.VisualOtaDispatchGuard;
import xiaozhi.modules.visualota.util.VisualOtaResourceType;

@Slf4j
@Service
@RequiredArgsConstructor
public class RoleDeployServiceImpl implements RoleDeployService {

    private final RoleDeployTaskDao taskDao;
    private final RolePackDao rolePackDao;
    private final DeviceVisualRoleDao visualRoleDao;
    private final RolePackService rolePackService;
    private final DeviceService deviceService;
    private final RolePackProperties properties;
    private final RolePackSigner signer;
    private final RolePackAuditService auditService;
    private final RedisUtils redisUtils;
    private final SysParamsService sysParamsService;
    private final RestTemplate restTemplate;
    private final VisualOtaDispatchGuard visualOtaDispatchGuard;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Override
    @Transactional(rollbackFor = Exception.class)
    public RoleDeployTaskVO deploy(Long userId, String packId, String deviceId) {
        signer.requireReady();
        if (StringUtils.isBlank(deviceId)) {
            throw new RenException("设备ID不能为空");
        }
        DeviceEntity device = deviceService.selectById(deviceId);
        if (device == null || device.getUserId() == null || !device.getUserId().equals(userId)) {
            // 故意模糊
            throw new RenException("无权向该设备部署角色");
        }

        RolePackEntity pack = rolePackService.requirePublished(packId);
        validateBoardAndFw(device, pack);

        RoleDeployTaskEntity active = findActiveTaskForUpdate(deviceId);
        if (active != null) {
            auditService.log("DEPLOY_CONFLICT", userId, deviceId, packId, active.getTaskId(),
                    "device already has active task", "E_BUSY");
            return toVo(active, pack.getDisplayName(), pack.getVersion());
        }

        String taskId = UUID.randomUUID().toString();
        IssuedDownload issued = issueSignedDownload(taskId, deviceId, pack);

        Map<String, Object> payload = buildUpdateSpinePayload(taskId, pack, issued.signature(), issued.downloadUrl());

        Date now = new Date();
        RoleDeployTaskEntity task = new RoleDeployTaskEntity();
        task.setTaskId(taskId);
        task.setDeviceId(deviceId);
        task.setRolePackId(pack.getId());
        task.setPackId(pack.getPackId());
        task.setRequestedBy(userId);
        task.setState(RolePackConstants.STATE_QUEUED);
        task.setProgress(0);
        task.setRetryCount(0);
        task.setAttemptCount(0);
        task.setDownloadToken(issued.token());
        task.setSignature(issued.signature());
        try {
            task.setPayloadJson(objectMapper.writeValueAsString(payload));
        } catch (Exception e) {
            throw new RenException("序列化任务载荷失败");
        }
        task.setCreatedAt(now);
        task.setUpdatedAt(now);
        taskDao.insert(task);

        auditService.log("DEPLOY_CREATE", userId, deviceId, packId, taskId, "queued", null);

        boolean sent = false;
        if (tryAcquireVisualDispatch(deviceId, taskId)) {
            sent = pushToDevice(deviceId, payload);
            if (!sent) {
                releaseVisualDispatch(deviceId, taskId);
            }
        } else {
            log.info(
                    "[update_spine] skip_push task_id={} device_id={} state=queued attempt_count=0 reason=visual_ota_blocked",
                    taskId, deviceId);
            auditService.log("DEPLOY_BLOCKED", userId, deviceId, packId, taskId,
                    "visual OTA slot held by other resource", "E_BUSY");
        }
        if (sent) {
            String leaseId = UUID.randomUUID().toString();
            long nextVersion = 1L;
            task.setState(RolePackConstants.STATE_SENT);
            task.setAttemptCount(1);
            task.setDeliveryLeaseId(leaseId);
            task.setDeliveryVersion(nextVersion);
            task.setClaimedSessionId(null);
            task.setLastDeliveredAt(new Date());
            task.setUpdatedAt(new Date());
            taskDao.updateById(task);
            auditService.log("DEPLOY_PUSH", userId, deviceId, packId, taskId,
                    "sent attempt_count=1 lease=" + leaseId, null);
            log.info(
                    "[update_spine] deliver task_id={} device_id={} state=sent attempt_count=1 "
                            + "delivery_version={} lease_id={} reason=deploy_push",
                    taskId, deviceId, nextVersion, leaseId);
        } else {
            auditService.log("DEPLOY_OFFLINE", userId, deviceId, packId, taskId,
                    "device offline, keep queued", null);
            log.info(
                    "[update_spine] skip_push task_id={} device_id={} state=queued attempt_count=0 reason=device_offline",
                    taskId, deviceId);
        }
        return toVo(task, pack.getDisplayName(), pack.getVersion());
    }

    @Override
    public RoleDeployTaskVO getTaskForUser(Long userId, String taskId) {
        RoleDeployTaskEntity task = requireTask(taskId);
        if (!task.getRequestedBy().equals(userId)) {
            DeviceEntity device = deviceService.selectById(task.getDeviceId());
            if (device == null || !userId.equals(device.getUserId())) {
                throw new RenException("无权查看该任务");
            }
        }
        RolePackEntity pack = rolePackService.getByPackId(task.getPackId());
        return toVo(task, pack != null ? pack.getDisplayName() : null,
                pack != null ? pack.getVersion() : null);
    }

    @Override
    public RoleDeployTaskVO getTaskInternal(String taskId) {
        RoleDeployTaskEntity task = requireTask(taskId);
        RolePackEntity pack = rolePackService.getByPackId(task.getPackId());
        return toVo(task, pack != null ? pack.getDisplayName() : null,
                pack != null ? pack.getVersion() : null);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public SpineOtaAckResultVO handleDeviceAck(String authenticatedDeviceId, SpineOtaAckDTO ack) {
        if (StringUtils.isBlank(authenticatedDeviceId)) {
            throw new RenException("缺少设备身份");
        }
        RoleDeployTaskEntity task = requireTask(ack.getTaskId());
        // 严格绑定 task_id + device_id：设备只能 ACK 自己的任务
        if (!authenticatedDeviceId.equals(task.getDeviceId())) {
            auditService.log("ACK_FORGE", null, authenticatedDeviceId, ack.getPackId(), ack.getTaskId(),
                    "device mismatch", "E_FORBIDDEN");
            throw new RenException("任务不属于当前设备");
        }
        if (!task.getPackId().equals(ack.getPackId())) {
            throw new RenException("pack_id 与任务不一致");
        }

        String newState = RoleDeployStateMachine.phaseToState(ack.getPhase());
        if (newState == null) {
            throw new RenException("无效 phase: " + ack.getPhase());
        }
        int progress = ack.getProgress() == null ? task.getProgress()
                : Math.max(0, Math.min(100, ack.getProgress()));

        if (RolePackConstants.STATE_COMPLETED.equals(newState)) {
            return handleSuccessAck(task);
        }
        if (RolePackConstants.STATE_FAILED.equals(newState)) {
            return handleFailedAck(task, ack, progress);
        }
        return handleProgressAck(task, newState, progress);
    }

    /**
     * spine_ota_status(success)：先原子完成中央任务，再允许 xiaozhi-server 回 spine_ota_ack。
     * 幂等：重复 success 直接返回 completed，不重建任务、不重投。
     */
    private SpineOtaAckResultVO handleSuccessAck(RoleDeployTaskEntity task) {
        String taskId = task.getTaskId();
        String deviceId = task.getDeviceId();
        String prevState = task.getState();
        Integer attemptCount = task.getAttemptCount() == null ? 0 : task.getAttemptCount();
        if (RolePackConstants.SUCCESS_STATES.contains(prevState)) {
            releaseVisualDispatch(deviceId, taskId);
            log.info(
                    "[update_spine] ack_success task_id={} device_id={} state={} attempt_count={} reason=idempotent_duplicate",
                    taskId, deviceId, prevState, attemptCount);
            return buildAckResult(taskId, deviceId, prevState, true, true, attemptCount);
        }
        if (!RoleDeployStateMachine.canComplete(prevState)) {
            auditService.log("ACK_REJECT", null, deviceId, task.getPackId(), taskId,
                    "illegal success from " + prevState, "E_STATE");
            log.warn(
                    "[update_spine] ack_reject task_id={} device_id={} old_state={} new_state=completed attempt_count={} reason=illegal_transition",
                    taskId, deviceId, prevState, attemptCount);
            throw new RenException("非法状态转换: " + prevState + " -> completed");
        }
        String version = rolePackService.getByPackId(task.getPackId()) != null
                ? rolePackService.getByPackId(task.getPackId()).getVersion() : null;
        Date now = new Date();
        // CAS：仅当 state 仍处于「活跃可完成」集合时才落 completed（不含 completed/succeeded），
        // 并发第二个 success 命中已 completed 行 → 影响 0 行 → 走 re-read 幂等分支。
        LambdaUpdateWrapper<RoleDeployTaskEntity> uw = new LambdaUpdateWrapper<>();
        uw.eq(RoleDeployTaskEntity::getTaskId, taskId)
                .eq(RoleDeployTaskEntity::getDeviceId, deviceId)
                .in(RoleDeployTaskEntity::getState, RolePackConstants.COMPLETABLE_ACTIVE_STATES)
                .set(RoleDeployTaskEntity::getState, RolePackConstants.STATE_COMPLETED)
                .set(RoleDeployTaskEntity::getProgress, 100)
                .set(RoleDeployTaskEntity::getErrorCode, null)
                .set(RoleDeployTaskEntity::getErrorMessage, null)
                .set(RoleDeployTaskEntity::getLastError, null)
                .set(RoleDeployTaskEntity::getCompletedAt, now)
                .set(RoleDeployTaskEntity::getCurrentRoleVersion, version)
                .set(RoleDeployTaskEntity::getUpdatedAt, now);
        int updated = taskDao.update(null, uw);
        if (updated == 0) {
            RoleDeployTaskEntity cur = requireTask(taskId);
            if (RolePackConstants.SUCCESS_STATES.contains(cur.getState())) {
                releaseVisualDispatch(deviceId, taskId);
                return buildAckResult(taskId, deviceId, cur.getState(), true, true, cur.getAttemptCount());
            }
            auditService.log("ACK_REJECT", null, deviceId, task.getPackId(), taskId,
                    "lost race to " + cur.getState(), "E_STATE");
            throw new RenException("任务状态已变更: " + cur.getState());
        }
        RoleDeployTaskEntity updatedTask = requireTask(taskId);
        upsertDeviceVisualRole(updatedTask);
        releaseVisualDispatch(deviceId, taskId);
        auditService.log("ACK_SUCCESS", null, deviceId, task.getPackId(), taskId, "success", null);
        log.info(
                "[update_spine] ack_success task_id={} device_id={} old_state={} new_state=completed attempt_count={} reason=phase_success",
                taskId, deviceId, prevState, attemptCount);
        return buildAckResult(taskId, deviceId, RolePackConstants.STATE_COMPLETED, true, false, attemptCount);
    }

    private SpineOtaAckResultVO handleFailedAck(RoleDeployTaskEntity task, SpineOtaAckDTO ack, int progress) {
        String taskId = task.getTaskId();
        String deviceId = task.getDeviceId();
        Integer attemptCount = task.getAttemptCount() == null ? 0 : task.getAttemptCount();
        if (RolePackConstants.TERMINAL_STATES.contains(task.getState())) {
            log.info(
                    "[update_spine] ack_failed task_id={} device_id={} state={} attempt_count={} reason=terminal_idempotent",
                    taskId, deviceId, task.getState(), attemptCount);
            return buildAckResult(taskId, deviceId, task.getState(), false, false, attemptCount);
        }
        String err = StringUtils.defaultIfBlank(ack.getError(), "E_UNKNOWN");
        Date now = new Date();
        LambdaUpdateWrapper<RoleDeployTaskEntity> uw = new LambdaUpdateWrapper<>();
        uw.eq(RoleDeployTaskEntity::getTaskId, taskId)
                .eq(RoleDeployTaskEntity::getDeviceId, deviceId)
                .in(RoleDeployTaskEntity::getState, RolePackConstants.ACTIVE_STATES)
                .set(RoleDeployTaskEntity::getState, RolePackConstants.STATE_FAILED)
                .set(RoleDeployTaskEntity::getProgress, progress)
                .set(RoleDeployTaskEntity::getErrorCode, err)
                .set(RoleDeployTaskEntity::getErrorMessage, ack.getError())
                .set(RoleDeployTaskEntity::getLastError,
                        err + (StringUtils.isNotBlank(ack.getError()) ? ": " + ack.getError() : ""))
                .set(RoleDeployTaskEntity::getCompletedAt, now)
                .set(RoleDeployTaskEntity::getUpdatedAt, now);
        int updated = taskDao.update(null, uw);
        if (updated == 0) {
            RoleDeployTaskEntity cur = requireTask(taskId);
            if (RolePackConstants.TERMINAL_STATES.contains(cur.getState())) {
                return buildAckResult(taskId, deviceId, cur.getState(), false, false, cur.getAttemptCount());
            }
        }
        String detail = "E_NVS".equals(err)
                ? "E_NVS 终态 failed，不自动重投；需人工检查/恢复设备 NVS"
                : ack.getError();
        auditService.log("ACK_FAILED", null, deviceId, task.getPackId(), taskId, detail, err);
        log.info(
                "[update_spine] ack_failed task_id={} device_id={} old_state={} new_state=failed attempt_count={} reason={}",
                taskId, deviceId, task.getState(), attemptCount, err);
        // 同步实体引用后再 maybeRetry，确保 updateById 不会抹掉审计字段
        task.setState(RolePackConstants.STATE_FAILED);
        task.setErrorCode(err);
        task.setErrorMessage(ack.getError());
        task.setLastError(err + (StringUtils.isNotBlank(ack.getError()) ? ": " + ack.getError() : ""));
        task.setCompletedAt(now);
        maybeRetry(task, err);
        releaseVisualDispatch(deviceId, taskId);
        return buildAckResult(taskId, deviceId, RolePackConstants.STATE_FAILED, false, false, attemptCount);
    }

    private SpineOtaAckResultVO handleProgressAck(RoleDeployTaskEntity task, String newState, int progress) {
        String taskId = task.getTaskId();
        String deviceId = task.getDeviceId();
        Integer attemptCount = task.getAttemptCount() == null ? 0 : task.getAttemptCount();
        String prevState = task.getState();
        // accepted 之后设备可能重发 waiting：已在 in_flight 则幂等忽略，不回退
        if (RolePackConstants.STATE_ACCEPTED.equals(newState)
                && RolePackConstants.IN_FLIGHT_STATES.contains(prevState)) {
            log.debug("忽略重复/过期 waiting ACK: task={} state={}", taskId, prevState);
            return buildAckResult(taskId, deviceId, prevState, false, false, attemptCount);
        }
        if (RolePackConstants.TERMINAL_STATES.contains(prevState)) {
            log.info(
                    "[update_spine] ack_progress task_id={} device_id={} state={} attempt_count={} reason=terminal_idempotent",
                    taskId, deviceId, prevState, attemptCount);
            return buildAckResult(taskId, deviceId, prevState, false, false, attemptCount);
        }
        if (!RoleDeployStateMachine.canTransition(prevState, newState)) {
            throw new RenException("非法状态转换: " + prevState + " -> " + newState);
        }
        Date now = new Date();
        LambdaUpdateWrapper<RoleDeployTaskEntity> uw = new LambdaUpdateWrapper<>();
        uw.eq(RoleDeployTaskEntity::getTaskId, taskId)
                .eq(RoleDeployTaskEntity::getDeviceId, deviceId)
                .in(RoleDeployTaskEntity::getState, RolePackConstants.ACTIVE_STATES)
                .set(RoleDeployTaskEntity::getState, newState)
                .set(RoleDeployTaskEntity::getProgress, progress)
                .set(RoleDeployTaskEntity::getUpdatedAt, now);
        if (RolePackConstants.STATE_ACCEPTED.equals(newState)) {
            uw.set(RoleDeployTaskEntity::getAcceptedAt, now);
        }
        taskDao.update(null, uw);
        log.info(
                "[update_spine] ack_progress task_id={} device_id={} old_state={} new_state={} attempt_count={} reason=phase_progress",
                taskId, deviceId, prevState, newState, attemptCount);
        return buildAckResult(taskId, deviceId, newState, false, false, attemptCount);
    }

    private SpineOtaAckResultVO buildAckResult(String taskId, String deviceId, String state,
            boolean completed, boolean duplicate, Integer attemptCount) {
        SpineOtaAckResultVO vo = new SpineOtaAckResultVO();
        vo.setTaskId(taskId);
        vo.setDeviceId(deviceId);
        vo.setState(state);
        vo.setCompleted(completed);
        vo.setDuplicate(duplicate);
        vo.setAttemptCount(attemptCount);
        return vo;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public Map<String, Object> buildPendingPushPayload(String deviceId, String claimedSessionId) {
        // FOR UPDATE 行锁：并发领取同一 device_id 的 pending 任务时串行化，
        // 后到的事务读到 attempt_count 已自增 + last_delivered_at 已更新，触发退避跳过，确保只投递一次。
        RoleDeployTaskEntity task = findActiveTaskForUpdate(deviceId);
        if (task == null) {
            log.info("[update_spine] pending_none device_id={} reason=no_active_task", deviceId);
            return null;
        }
        if (!RolePackConstants.REDELIVERABLE_STATES.contains(task.getState())) {
            log.info(
                    "[update_spine] pending_skip task_id={} device_id={} state={} attempt_count={} reason=not_redeliverable",
                    task.getTaskId(), deviceId, task.getState(), task.getAttemptCount());
            return null;
        }
        if (RolePackConstants.TERMINAL_STATES.contains(task.getState())) {
            return null;
        }

        int effectiveAttempts = task.getAttemptCount() == null ? 0 : task.getAttemptCount();
        boolean persistAttemptCompat = false;
        // 兼容升级前任务：已有 last_delivered_at 但 attempt_count 仍为 0
        if (effectiveAttempts == 0 && task.getLastDeliveredAt() != null) {
            effectiveAttempts = 1;
            task.setAttemptCount(1);
            persistAttemptCompat = true;
        }

        SpineRedeliveryPolicy.Action action = SpineRedeliveryPolicy.decide(
                effectiveAttempts,
                task.getLastDeliveredAt(),
                properties.getMaxRedeliverAttempts(),
                properties.getRedeliverBackoffBaseMs(),
                System.currentTimeMillis());

        if (action == SpineRedeliveryPolicy.Action.SKIP_BACKOFF) {
            long waitMs = SpineRedeliveryPolicy.backoffMsAfterAttempts(
                    effectiveAttempts,
                    properties.getRedeliverBackoffBaseMs());
            log.info(
                    "[update_spine] pending_skip task_id={} device_id={} state={} attempt_count={} reason=backoff wait_ms={}",
                    task.getTaskId(), deviceId, task.getState(), effectiveAttempts, waitMs);
            if (persistAttemptCompat) {
                task.setUpdatedAt(new Date());
                taskDao.updateById(task);
            }
            return null;
        }
        if (action == SpineRedeliveryPolicy.Action.STOP_MAX_ATTEMPTS) {
            markNeedsManualReview(task, RolePackConstants.ERR_MAX_REDELIVER,
                    "max redeliver attempts reached: " + properties.getMaxRedeliverAttempts());
            log.warn(
                    "[update_spine] pending_stop task_id={} device_id={} state={} attempt_count={} reason=max_attempts",
                    task.getTaskId(), deviceId, task.getState(), effectiveAttempts);
            return null;
        }

        RolePackEntity pack = rolePackService.getByPackId(task.getPackId());
        if (pack == null || !RolePackConstants.STATUS_PUBLISHED.equals(pack.getStatus())) {
            log.info(
                    "[update_spine] pending_skip task_id={} device_id={} state={} attempt_count={} reason=pack_unavailable",
                    task.getTaskId(), deviceId, task.getState(), task.getAttemptCount());
            return null;
        }
        if (!tryAcquireVisualDispatch(deviceId, task.getTaskId())) {
            log.info(
                    "[update_spine] pending_skip task_id={} device_id={} state={} attempt_count={} reason=visual_ota_blocked",
                    task.getTaskId(), deviceId, task.getState(), task.getAttemptCount());
            if (persistAttemptCompat) {
                task.setUpdatedAt(new Date());
                taskDao.updateById(task);
            }
            return null;
        }
        // 过期 token 不得重发：每次重投重新生成 URL + 完整签名
        IssuedDownload issued = issueSignedDownload(task.getTaskId(), deviceId, pack);
        task.setDownloadToken(issued.token());
        task.setSignature(issued.signature());
        Map<String, Object> payload = buildUpdateSpinePayload(task.getTaskId(), pack, issued.signature(),
                issued.downloadUrl());
        try {
            task.setPayloadJson(objectMapper.writeValueAsString(payload));
        } catch (Exception ignored) {
        }
        int nextAttempt = effectiveAttempts + 1;
        // 不可复用 lease + 单调 version：release 身份绝不依赖可回退的 attempt_count
        String leaseId = UUID.randomUUID().toString();
        long nextVersion = (task.getDeliveryVersion() == null ? 0L : task.getDeliveryVersion()) + 1L;
        Date now = new Date();
        task.setAttemptCount(nextAttempt);
        task.setState(RolePackConstants.STATE_SENT);
        task.setDeliveryLeaseId(leaseId);
        task.setDeliveryVersion(nextVersion);
        task.setClaimedSessionId(StringUtils.isNotBlank(claimedSessionId) ? claimedSessionId : null);
        task.setLastDeliveredAt(now);
        task.setNextAttemptAt(new Date(now.getTime()
                + SpineRedeliveryPolicy.backoffMsAfterAttempts(nextAttempt,
                        properties.getRedeliverBackoffBaseMs())));
        task.setUpdatedAt(now);
        task.setLastError(null);
        taskDao.updateById(task);
        auditService.log("DEPLOY_REDELIVER", null, deviceId, pack.getPackId(), task.getTaskId(),
                "reconnect-resign attempt_count=" + nextAttempt + " lease=" + leaseId
                        + " version=" + nextVersion,
                null);
        log.info(
                "[update_spine] deliver task_id={} device_id={} state=sent attempt_count={} "
                        + "delivery_version={} lease_id={} session_id={} reason=reconnect_redeliver next_attempt_at={}",
                task.getTaskId(), deviceId, nextAttempt, nextVersion, leaseId,
                task.getClaimedSessionId(), task.getNextAttemptAt());
        // 内部键：controller 剥离后不下发设备；供 xiaozhi-server stale 精确释放
        payload.put(RolePackConstants.PENDING_CLAIM_ATTEMPT_KEY, nextAttempt);
        payload.put(RolePackConstants.PENDING_CLAIM_LEASE_KEY, leaseId);
        payload.put(RolePackConstants.PENDING_CLAIM_VERSION_KEY, nextVersion);
        if (task.getClaimedSessionId() != null) {
            payload.put(RolePackConstants.PENDING_CLAIM_SESSION_KEY, task.getClaimedSessionId());
        }
        return payload;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void releasePendingDelivery(String deviceId, String taskId, String deliveryLeaseId,
            String claimedSessionId) {
        if (StringUtils.isBlank(deviceId) || StringUtils.isBlank(taskId)) {
            throw new RenException("缺少 deviceId/taskId");
        }
        if (StringUtils.isBlank(deliveryLeaseId)) {
            throw new RenException("缺少 deliveryLeaseId");
        }
        RoleDeployTaskEntity task = requireTask(taskId);
        if (!deviceId.equals(task.getDeviceId())) {
            auditService.log("RELEASE_FORGE", null, deviceId, task.getPackId(), taskId,
                    "device mismatch", "E_FORBIDDEN");
            throw new RenException("任务不属于当前设备");
        }
        // ABA 防护：仅当 lease 仍为本次领取的不可复用 UUID 时才回滚；
        // delivery_version 永不回退；lease 清空后旧 release 重放命中 0 行。
        LambdaUpdateWrapper<RoleDeployTaskEntity> uw = new LambdaUpdateWrapper<>();
        uw.eq(RoleDeployTaskEntity::getTaskId, taskId)
                .eq(RoleDeployTaskEntity::getDeviceId, deviceId)
                .eq(RoleDeployTaskEntity::getState, RolePackConstants.STATE_SENT)
                .eq(RoleDeployTaskEntity::getDeliveryLeaseId, deliveryLeaseId);
        if (StringUtils.isNotBlank(claimedSessionId)) {
            uw.eq(RoleDeployTaskEntity::getClaimedSessionId, claimedSessionId);
        }
        uw.set(RoleDeployTaskEntity::getState, RolePackConstants.STATE_QUEUED)
                .set(RoleDeployTaskEntity::getDeliveryLeaseId, null)
                .set(RoleDeployTaskEntity::getClaimedSessionId, null)
                .setSql("attempt_count = GREATEST(IFNULL(attempt_count, 0) - 1, 0)")
                .set(RoleDeployTaskEntity::getLastDeliveredAt, null)
                .set(RoleDeployTaskEntity::getNextAttemptAt, null)
                .set(RoleDeployTaskEntity::getLastError, null)
                .set(RoleDeployTaskEntity::getUpdatedAt, new Date());
        // 注意：故意不 set delivery_version —— 版本只增不减
        int updated = taskDao.update(null, uw);
        if (updated == 0) {
            RoleDeployTaskEntity cur = requireTask(taskId);
            log.info(
                    "[update_spine] release_skip task_id={} device_id={} state={} lease_id={} "
                            + "delivery_version={} claimed_lease={} reason=lease_mismatch_or_advanced",
                    taskId, deviceId, cur.getState(), cur.getDeliveryLeaseId(),
                    cur.getDeliveryVersion(), deliveryLeaseId);
            return;
        }
        RoleDeployTaskEntity after = requireTask(taskId);
        releaseVisualDispatch(deviceId, taskId);
        auditService.log("DEPLOY_RELEASE", null, deviceId, task.getPackId(), taskId,
                "release lease=" + deliveryLeaseId + " version_kept=" + after.getDeliveryVersion(), null);
        log.info(
                "[update_spine] release task_id={} device_id={} prev_state=sent new_state=queued "
                        + "delivery_version={} lease_cleared={} reason=stale_release",
                taskId, deviceId, after.getDeliveryVersion(), deliveryLeaseId);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public List<RoleDeployTaskVO> cancelPendingUpdateSpine(String deviceId, String reason, Long actorUserId) {
        if (StringUtils.isBlank(deviceId)) {
            throw new RenException("设备ID不能为空");
        }
        if (actorUserId != null) {
            DeviceEntity device = deviceService.selectById(deviceId);
            if (device == null || device.getUserId() == null || !device.getUserId().equals(actorUserId)) {
                throw new RenException("无权取消该设备的角色任务");
            }
        }
        String cancelReason = StringUtils.defaultIfBlank(reason, "manual_cancel");
        List<RoleDeployTaskEntity> tasks = taskDao.selectList(new LambdaQueryWrapper<RoleDeployTaskEntity>()
                .eq(RoleDeployTaskEntity::getDeviceId, deviceId)
                .in(RoleDeployTaskEntity::getState, RolePackConstants.CANCELABLE_UPDATE_SPINE_STATES)
                .orderByDesc(RoleDeployTaskEntity::getCreatedAt));
        List<RoleDeployTaskVO> cancelled = new java.util.ArrayList<>();
        Date now = new Date();
        for (RoleDeployTaskEntity task : tasks) {
            // 本表任务均为 update_spine；再校验 payload 以防脏数据
            if (!isUpdateSpineTask(task)) {
                continue;
            }
            task.setState(RolePackConstants.STATE_CANCELLED);
            task.setCancelledAt(now);
            task.setCancelReason(cancelReason);
            task.setLastError(RolePackConstants.ERR_MANUAL_CANCEL + ": " + cancelReason);
            task.setErrorCode(RolePackConstants.ERR_MANUAL_CANCEL);
            task.setErrorMessage(cancelReason);
            task.setCompletedAt(now);
            task.setUpdatedAt(now);
            taskDao.updateById(task);
            releaseVisualDispatch(deviceId, task.getTaskId());
            auditService.log("DEPLOY_CANCEL", actorUserId, deviceId, task.getPackId(), task.getTaskId(),
                    cancelReason, RolePackConstants.ERR_MANUAL_CANCEL);
            log.info(
                    "[update_spine] cancel task_id={} device_id={} state=cancelled attempt_count={} reason={}",
                    task.getTaskId(), deviceId, task.getAttemptCount(), cancelReason);
            RolePackEntity pack = rolePackService.getByPackId(task.getPackId());
            cancelled.add(toVo(task, pack != null ? pack.getDisplayName() : null,
                    pack != null ? pack.getVersion() : null));
        }
        return cancelled;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public RoleDeployTaskVO markAbnormalDisconnectAfterUpdateSpine(String deviceId, String taskId) {
        if (StringUtils.isBlank(deviceId)) {
            throw new RenException("设备ID不能为空");
        }
        RoleDeployTaskEntity task;
        if (StringUtils.isNotBlank(taskId)) {
            task = requireTask(taskId);
            if (!deviceId.equals(task.getDeviceId())) {
                throw new RenException("任务不属于当前设备");
            }
        } else {
            task = findActiveTask(deviceId);
        }
        if (task == null) {
            return null;
        }
        if (RolePackConstants.TERMINAL_STATES.contains(task.getState())) {
            log.info(
                    "[update_spine] abnormal_ignore task_id={} device_id={} state={} attempt_count={} reason=already_terminal",
                    task.getTaskId(), deviceId, task.getState(), task.getAttemptCount());
            RolePackEntity pack = rolePackService.getByPackId(task.getPackId());
            return toVo(task, pack != null ? pack.getDisplayName() : null,
                    pack != null ? pack.getVersion() : null);
        }
        // 仅对尚未进入下载进度的任务停自动投递（queued/retrying/sent）
        if (!RolePackConstants.CANCELABLE_UPDATE_SPINE_STATES.contains(task.getState())) {
            log.info(
                    "[update_spine] abnormal_ignore task_id={} device_id={} state={} attempt_count={} reason=in_progress",
                    task.getTaskId(), deviceId, task.getState(), task.getAttemptCount());
            return null;
        }
        int attempts = task.getAttemptCount() == null ? 0 : task.getAttemptCount();
        if (attempts <= 0) {
            return null;
        }
        markNeedsManualReview(task, RolePackConstants.ERR_ABNORMAL_DISCONNECT,
                "abnormal disconnect after update_spine");
        releaseVisualDispatch(deviceId, task.getTaskId());
        log.warn(
                "[update_spine] abnormal_stop task_id={} device_id={} state={} attempt_count={} reason=abnormal_disconnect",
                task.getTaskId(), deviceId, task.getState(), task.getAttemptCount());
        RolePackEntity pack = rolePackService.getByPackId(task.getPackId());
        return toVo(task, pack != null ? pack.getDisplayName() : null,
                pack != null ? pack.getVersion() : null);
    }

    private void markNeedsManualReview(RoleDeployTaskEntity task, String errorCode, String detail) {
        Date now = new Date();
        task.setState(RolePackConstants.STATE_NEEDS_MANUAL_REVIEW);
        task.setErrorCode(errorCode);
        task.setErrorMessage(detail);
        task.setLastError(errorCode + ": " + detail);
        task.setCompletedAt(now);
        task.setUpdatedAt(now);
        taskDao.updateById(task);
        releaseVisualDispatch(task.getDeviceId(), task.getTaskId());
        auditService.log("DEPLOY_NEEDS_REVIEW", null, task.getDeviceId(), task.getPackId(), task.getTaskId(),
                detail, errorCode);
    }

    private boolean isUpdateSpineTask(RoleDeployTaskEntity task) {
        if (task == null) {
            return false;
        }
        String json = task.getPayloadJson();
        if (StringUtils.isBlank(json)) {
            // 历史任务缺 payload 时，本表任务默认即为 update_spine
            return true;
        }
        return json.contains("\"command\":\"" + RolePackConstants.CMD_UPDATE_SPINE + "\"")
                || json.contains("\"command\": \"" + RolePackConstants.CMD_UPDATE_SPINE + "\"");
    }

    @Override
    public byte[] downloadByToken(String token) {
        if (StringUtils.isBlank(token)) {
            throw new RenException("无效下载令牌");
        }
        // 不向调用方回显完整 token
        Object raw = redisUtils.get(RolePackConstants.REDIS_DOWNLOAD_PREFIX + token);
        if (raw == null) {
            throw new RenException("下载令牌无效或已过期");
        }
        Map<String, Object> bind;
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> parsed = objectMapper.readValue(raw.toString(), Map.class);
            bind = parsed;
        } catch (Exception e) {
            throw new RenException("下载令牌数据损坏");
        }
        String taskId = String.valueOf(bind.get("taskId"));
        String packId = String.valueOf(bind.get("packId"));
        String objectKey = String.valueOf(bind.get("objectKey"));
        Long packPk = Long.valueOf(String.valueOf(bind.get("packPk")));

        RoleDeployTaskEntity task = requireTask(taskId);
        if (!packId.equals(task.getPackId())) {
            throw new RenException("令牌与任务不匹配");
        }
        if (RolePackConstants.TERMINAL_STATES.contains(task.getState())
                || RolePackConstants.STATE_EXPIRED.equals(task.getState())) {
            throw new RenException("任务已结束，下载无效");
        }

        String countKey = RolePackConstants.REDIS_DOWNLOAD_COUNT_PREFIX + token;
        int count = 0;
        Object countObj = redisUtils.get(countKey);
        if (countObj instanceof Number n) {
            count = n.intValue();
        }
        // 次数用尽：使当前 token 失效，但任务保持进行中，设备重连可重新签发
        if (count >= properties.getDownloadMaxCount()) {
            redisUtils.delete(RolePackConstants.REDIS_DOWNLOAD_PREFIX + token);
            redisUtils.delete(countKey);
            throw new RenException("下载次数已用尽，请等待任务重投后重试");
        }
        redisUtils.set(countKey, count + 1, properties.getDownloadTokenTtlSeconds());

        RolePackEntity pack = rolePackDao.selectById(packPk);
        if (pack == null || !objectKey.equals(pack.getObjectKey())) {
            throw new RenException("角色包不存在或 object_key 不匹配");
        }
        byte[] data = rolePackService.readPackBytes(pack);
        if (task.getPayloadJson() != null) {
            // Content-Length 由调用方使用 body.length；此处断言与任务 size 一致
            if (pack.getSize() != null && data.length != pack.getSize().intValue()) {
                throw new RenException("包大小与任务元数据不一致");
            }
        }
        return data;
    }

    @Override
    public String resolveContentDisposition(String token) {
        return "attachment; filename=\"spine.bin\"";
    }

    private record IssuedDownload(String token, String downloadUrl, String signature) {
    }

    /**
     * 生成短时 token → 构造 https 下载 URL → 再对该 URL 的 origin+path 签名（签名后禁止改 host/path）。
     */
    private IssuedDownload issueSignedDownload(String taskId, String deviceId, RolePackEntity pack) {
        String token = java.util.UUID.randomUUID().toString().replace("-", "")
                + java.util.UUID.randomUUID().toString().replace("-", "");
        String downloadUrl = buildDownloadUrl(token);
        // 先得到最终 URL，再签名（query 不参与）
        String signature = signer.signTask(taskId, pack.getPackId(), pack.getPackId(), pack.getVersion(),
                pack.getSize(), pack.getSha256(), pack.getMinFw(), downloadUrl);

        Map<String, Object> bind = new HashMap<>();
        bind.put("taskId", taskId);
        bind.put("deviceId", deviceId);
        bind.put("packId", pack.getPackId());
        bind.put("objectKey", pack.getObjectKey());
        bind.put("packPk", pack.getId());
        bind.put("exp", System.currentTimeMillis() + properties.getDownloadTokenTtlSeconds() * 1000L);
        try {
            redisUtils.set(RolePackConstants.REDIS_DOWNLOAD_PREFIX + token,
                    objectMapper.writeValueAsString(bind), properties.getDownloadTokenTtlSeconds());
        } catch (Exception e) {
            throw new RenException("写入下载令牌失败");
        }
        redisUtils.set(RolePackConstants.REDIS_DOWNLOAD_COUNT_PREFIX + token, 0,
                properties.getDownloadTokenTtlSeconds());
        return new IssuedDownload(token, downloadUrl, signature);
    }

    private void maybeRetry(RoleDeployTaskEntity task, String errorCode) {
        if (!RoleDeployStateMachine.isRetryableError(errorCode)) {
            return;
        }
        if (task.getRetryCount() != null && task.getRetryCount() >= properties.getMaxRetryCount()) {
            auditService.log("RETRY_EXHAUSTED", null, task.getDeviceId(), task.getPackId(), task.getTaskId(),
                    "max retry", errorCode);
            // ACK 可重试耗尽：进入人工复核，避免靠重连无限投递
            markNeedsManualReview(task, errorCode, "ACK retry exhausted");
            return;
        }
        task.setRetryCount(task.getRetryCount() == null ? 1 : task.getRetryCount() + 1);
        task.setState(RolePackConstants.STATE_RETRYING);
        task.setProgress(0);
        task.setCompletedAt(null);
        task.setUpdatedAt(new Date());
        taskDao.updateById(task);
        auditService.log("RETRY_QUEUE", null, task.getDeviceId(), task.getPackId(), task.getTaskId(),
                "retry=" + task.getRetryCount(), errorCode);
    }

    private void upsertDeviceVisualRole(RoleDeployTaskEntity task) {
        RolePackEntity pack = rolePackService.getByPackId(task.getPackId());
        if (pack == null) {
            return;
        }
        DeviceVisualRoleEntity existing = visualRoleDao.selectOne(new LambdaQueryWrapper<DeviceVisualRoleEntity>()
                .eq(DeviceVisualRoleEntity::getDeviceId, task.getDeviceId())
                .last("LIMIT 1"));
        Date now = new Date();
        if (existing == null) {
            DeviceVisualRoleEntity e = new DeviceVisualRoleEntity();
            e.setDeviceId(task.getDeviceId());
            e.setPackId(pack.getPackId());
            e.setVersion(pack.getVersion());
            e.setTaskId(task.getTaskId());
            e.setUpdatedAt(now);
            visualRoleDao.insert(e);
        } else {
            existing.setPackId(pack.getPackId());
            existing.setVersion(pack.getVersion());
            existing.setTaskId(task.getTaskId());
            existing.setUpdatedAt(now);
            visualRoleDao.updateById(existing);
        }
    }

    private void validateBoardAndFw(DeviceEntity device, RolePackEntity pack) {
        List<String> allow;
        try {
            allow = objectMapper.readValue(pack.getBoardModelAllowlist(),
                    objectMapper.getTypeFactory().constructCollectionType(List.class, String.class));
        } catch (Exception e) {
            throw new RenException("角色包型号白名单无效");
        }
        String board = device.getBoard();
        if (StringUtils.isBlank(board) || allow.stream().noneMatch(b -> b.equalsIgnoreCase(board))) {
            throw new RenException("设备型号不在角色包支持列表中");
        }
        String fw = device.getAppVersion();
        if (StringUtils.isBlank(fw)) {
            throw new RenException("设备固件版本未知，无法校验 min_fw");
        }
        if (VersionCompareUtil.compare(fw, pack.getMinFw()) < 0) {
            throw new RenException("设备固件版本低于角色包要求 min_fw=" + pack.getMinFw());
        }
    }

    private RoleDeployTaskEntity findActiveTask(String deviceId) {
        return taskDao.selectOne(new LambdaQueryWrapper<RoleDeployTaskEntity>()
                .eq(RoleDeployTaskEntity::getDeviceId, deviceId)
                .in(RoleDeployTaskEntity::getState, RolePackConstants.ACTIVE_STATES)
                .orderByDesc(RoleDeployTaskEntity::getCreatedAt)
                .last("LIMIT 1"));
    }

    /**
     * 领取/冲突检查专用：对设备活跃任务行加排他锁（InnoDB FOR UPDATE）。
     * 必须在 @Transactional 内调用；锁定直到事务提交，用于防止多 worker 并发领取同一 pending 任务。
     * 注意：当设备无活跃任务（不存在待锁行）时 FOR UPDATE 无法锁住 gap，
     * deploy() 创建任务仍需依赖 ai_role_deploy_task 的 (device_id, state) 唯一约束兜底。
     */
    private RoleDeployTaskEntity findActiveTaskForUpdate(String deviceId) {
        return taskDao.selectOne(new LambdaQueryWrapper<RoleDeployTaskEntity>()
                .eq(RoleDeployTaskEntity::getDeviceId, deviceId)
                .in(RoleDeployTaskEntity::getState, RolePackConstants.ACTIVE_STATES)
                .orderByDesc(RoleDeployTaskEntity::getCreatedAt)
                .last("LIMIT 1 FOR UPDATE"));
    }

    private RoleDeployTaskEntity requireTask(String taskId) {
        RoleDeployTaskEntity task = taskDao.selectOne(new LambdaQueryWrapper<RoleDeployTaskEntity>()
                .eq(RoleDeployTaskEntity::getTaskId, taskId)
                .last("LIMIT 1"));
        if (task == null) {
            throw new RenException("任务不存在");
        }
        return task;
    }

    private Map<String, Object> buildUpdateSpinePayload(String taskId, RolePackEntity pack,
            String signature, String url) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("type", RolePackConstants.MSG_TYPE_SYSTEM);
        payload.put("command", RolePackConstants.CMD_UPDATE_SPINE);
        payload.put("task_id", taskId);
        payload.put("pack_id", pack.getPackId());
        payload.put("role_id", pack.getPackId());
        payload.put("version", pack.getVersion());
        // 使用 int 避免全局 Jackson Long→String，保证设备收到 JSON number
        payload.put("size", pack.getSize() == null ? 0 : pack.getSize().intValue());
        payload.put("sha256", pack.getSha256().toLowerCase());
        payload.put("signature", signature);
        payload.put("url", url);
        payload.put("min_fw", pack.getMinFw());
        return payload;
    }

    private String buildDownloadUrl(String token) {
        String base = DownloadBaseUrlValidator.requireValid(properties.getDownloadBaseUrl());
        return base + "/role-packs/download/" + token;
    }

    private boolean tryAcquireVisualDispatch(String deviceId, String taskId) {
        VisualOtaDispatchGuard.ClaimResult result = visualOtaDispatchGuard.tryClaim(
                deviceId, VisualOtaResourceType.SPINE, taskId);
        return result == VisualOtaDispatchGuard.ClaimResult.CLAIMED
                || result == VisualOtaDispatchGuard.ClaimResult.ALREADY_HELD_BY_SELF;
    }

    private void releaseVisualDispatch(String deviceId, String taskId) {
        visualOtaDispatchGuard.release(deviceId, VisualOtaResourceType.SPINE, taskId);
    }

    private boolean pushToDevice(String deviceId, Map<String, Object> payload) {
        String pushUrl = properties.getPushUrl();
        if (StringUtils.isBlank(pushUrl)) {
            log.warn("未配置 xiaozhi.role-pack.push-url，跳过推送");
            return false;
        }
        try {
            String secret = sysParamsService.getValue(Constant.SERVER_SECRET, true);
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            if (StringUtils.isNotBlank(secret)) {
                headers.setBearerAuth(secret);
            }
            Map<String, Object> body = new HashMap<>();
            body.put("device_id", deviceId);
            body.put("payload", payload);
            HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);
            String resp = restTemplate.postForObject(pushUrl, entity, String.class);
            if (StringUtils.isBlank(resp)) {
                return false;
            }
            // {"ok":true/false,"sent":...}
            return resp.contains("\"ok\":true") || resp.contains("\"sent\":true");
        } catch (Exception e) {
            log.warn("推送 update_spine 失败 deviceId={}: {}", deviceId, e.getMessage());
            return false;
        }
    }

    private RoleDeployTaskVO toVo(RoleDeployTaskEntity task, String displayName, String version) {
        RoleDeployTaskVO vo = new RoleDeployTaskVO();
        vo.setTaskId(task.getTaskId());
        vo.setDeviceId(task.getDeviceId());
        vo.setPackId(task.getPackId());
        vo.setDisplayName(displayName);
        vo.setVersion(version);
        vo.setState(task.getState());
        vo.setProgress(task.getProgress());
        vo.setErrorCode(task.getErrorCode());
        vo.setErrorMessage(task.getErrorMessage());
        vo.setRetryCount(task.getRetryCount());
        vo.setAttemptCount(task.getAttemptCount());
        vo.setCreatedAt(task.getCreatedAt());
        vo.setUpdatedAt(task.getUpdatedAt());
        vo.setCompletedAt(task.getCompletedAt());
        vo.setCancelledAt(task.getCancelledAt());
        vo.setCancelReason(task.getCancelReason());
        vo.setLastError(task.getLastError());
        vo.setCurrentRoleVersion(task.getCurrentRoleVersion());
        return vo;
    }
}
