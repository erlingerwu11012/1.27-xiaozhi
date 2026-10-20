package xiaozhi.modules.device.service.impl;

import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.apache.commons.lang3.StringUtils;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.client.RestTemplate;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.constant.Constant;
import xiaozhi.modules.device.dao.DeviceWsRevokeOutboxDao;
import xiaozhi.modules.device.entity.DeviceWsRevokeOutboxEntity;
import xiaozhi.modules.sys.service.SysParamsService;

/**
 * 解绑/禁用后向 xiaozhi-server 同步推送单设备 revoke。
 * <p>事务提交后立即同步 HTTP 调用并等待 Python 返回 ok 确认；
 * 成功 → 标记 outbox delivered（同步已关闭）；
 * 失败 → outbox 保留并由定时任务重试（仅等待重试，不得称为立即）。
 * 握手侧无论通知是否成功，均按 auth-state fail-closed 拒绝旧 token。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DeviceWsRevokeNotifyService {

    private static final String REVOKE_URL_PARAM = "server.websocket_revoke_url";
    private static final String DEFAULT_REVOKE_URL = "http://127.0.0.1:8006/api/v1/device/revoke";

    private final RestTemplate restTemplate;
    private final SysParamsService sysParamsService;
    private final DeviceWsRevokeOutboxDao revokeOutboxDao;

    public void scheduleNotifyAfterCommit(String normalizedDeviceId, long credentialVersion, String status) {
        if (!TransactionSynchronizationManager.isSynchronizationActive()) {
            boolean syncOk = tryNotify(normalizedDeviceId, credentialVersion, status);
            log.info("[ws_revoke] sync_notify device_id_set=true sync_closed={} outbox_pending={}",
                    syncOk, !syncOk);
            return;
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                boolean syncOk = tryNotify(normalizedDeviceId, credentialVersion, status);
                log.info("[ws_revoke] sync_notify device_id_set=true sync_closed={} outbox_pending={}",
                        syncOk, !syncOk);
            }
        });
    }

    /**
     * 同步调用 Python revoke；仅当 HTTP 2xx 且 body.ok=true 时视为已处理确认。
     */
    public boolean tryNotify(String normalizedDeviceId, long credentialVersion, String status) {
        String url = resolveRevokeUrl();
        String secret = sysParamsService.getValue(Constant.SERVER_SECRET, true);
        if (StringUtils.isBlank(secret) || "null".equals(secret)) {
            log.warn("[ws_revoke] skip notify reason=secret_missing outbox_pending=true");
            return false;
        }
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.setBearerAuth(secret);
            Map<String, Object> body = new HashMap<>();
            body.put("device_id", normalizedDeviceId);
            body.put("credential_version", credentialVersion);
            body.put("status", status);
            HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);
            ResponseEntity<String> resp = restTemplate.postForEntity(url, entity, String.class);
            boolean ok = resp.getStatusCode().is2xxSuccessful()
                    && resp.getBody() != null
                    && (resp.getBody().contains("\"ok\":true") || resp.getBody().contains("\"ok\": true"));
            if (ok) {
                markLatestOutboxDelivered(normalizedDeviceId, credentialVersion);
                log.info("[ws_revoke] sync_closed=true device_id_set=true");
            } else {
                log.warn("[ws_revoke] sync_closed=false outbox_pending=true http_status={}",
                        resp.getStatusCode().value());
            }
            return ok;
        } catch (Exception e) {
            log.warn("[ws_revoke] sync_closed=false outbox_pending=true err_type={}",
                    e.getClass().getSimpleName());
            return false;
        }
    }

    /** 每 30s 重试未投递 outbox（最多读 50 条）。 */
    @Scheduled(fixedDelay = 30000L, initialDelay = 45000L)
    public void retryPendingOutbox() {
        Date now = new Date();
        List<DeviceWsRevokeOutboxEntity> pending = revokeOutboxDao.selectList(
                new QueryWrapper<DeviceWsRevokeOutboxEntity>()
                        .isNull("delivered_at")
                        .le("next_attempt_at", now)
                        .orderByAsc("id")
                        .last("LIMIT 50"));
        for (DeviceWsRevokeOutboxEntity row : pending) {
            boolean ok = tryNotify(row.getDeviceId(), row.getCredentialVersion(), row.getStatus());
            int attempts = row.getAttempts() == null ? 0 : row.getAttempts();
            row.setAttempts(attempts + 1);
            if (ok) {
                row.setDeliveredAt(new Date());
                row.setLastError(null);
            } else {
                // 指数退避上限 10 分钟
                long backoffMs = Math.min(600_000L, 5_000L * (1L << Math.min(attempts, 6)));
                row.setNextAttemptAt(new Date(System.currentTimeMillis() + backoffMs));
                row.setLastError("notify_failed");
            }
            revokeOutboxDao.updateById(row);
        }
    }

    private void markLatestOutboxDelivered(String deviceId, long version) {
        List<DeviceWsRevokeOutboxEntity> rows = revokeOutboxDao.selectList(
                new QueryWrapper<DeviceWsRevokeOutboxEntity>()
                        .eq("device_id", deviceId)
                        .eq("credential_version", version)
                        .isNull("delivered_at")
                        .orderByDesc("id")
                        .last("LIMIT 5"));
        Date now = new Date();
        for (DeviceWsRevokeOutboxEntity row : rows) {
            row.setDeliveredAt(now);
            row.setLastError(null);
            revokeOutboxDao.updateById(row);
        }
    }

    private String resolveRevokeUrl() {
        String v = sysParamsService.getValue(REVOKE_URL_PARAM, true);
        if (StringUtils.isNotBlank(v) && !"null".equals(v)) {
            return v.trim();
        }
        return DEFAULT_REVOKE_URL;
    }
}
