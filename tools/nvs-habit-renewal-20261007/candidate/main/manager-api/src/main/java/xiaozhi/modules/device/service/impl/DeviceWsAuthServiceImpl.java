package xiaozhi.modules.device.service.impl;

import java.util.Date;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.constant.Constant;
import xiaozhi.modules.device.dao.DeviceWsAuthDao;
import xiaozhi.modules.device.dao.DeviceWsRevokeOutboxDao;
import xiaozhi.modules.device.entity.DeviceWsAuthEntity;
import xiaozhi.modules.device.entity.DeviceWsRevokeOutboxEntity;
import xiaozhi.modules.device.service.DeviceWsAuthService;
import xiaozhi.modules.device.util.DeviceBootstrapCrypto;
import xiaozhi.modules.device.util.MacAddressUtils;
import xiaozhi.modules.device.vo.DeviceWsAuthStateVO;
import xiaozhi.modules.sys.service.SysParamsService;

@Slf4j
@Service
@RequiredArgsConstructor
public class DeviceWsAuthServiceImpl implements DeviceWsAuthService {

    private final DeviceWsAuthDao deviceWsAuthDao;
    private final DeviceWsRevokeOutboxDao revokeOutboxDao;
    private final SysParamsService sysParamsService;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public long ensureActiveForIssue(String deviceIdOrMac) {
        String normalized = requireNormalized(deviceIdOrMac);
        DeviceWsAuthEntity row = selectForUpdate(normalized);
        Date now = new Date();
        if (row == null) {
            row = newRow(normalized, 1L, DeviceWsAuthEntity.STATUS_ACTIVE, now);
            // 无 bootstrap 时不在此处明文返回；调用方应走 provisionNewBootstrap
            deviceWsAuthDao.insert(row);
            return 1L;
        }
        if (DeviceWsAuthEntity.STATUS_ACTIVE.equals(row.getStatus())) {
            return row.getCredentialVersion() == null ? 1L : row.getCredentialVersion();
        }
        // unbound/disabled → 重新绑定：递增 version；legacy 边界保留；bootstrap 由 provision 轮转
        long next = (row.getCredentialVersion() == null ? 0L : row.getCredentialVersion()) + 1L;
        row.setCredentialVersion(next);
        row.setStatus(DeviceWsAuthEntity.STATUS_ACTIVE);
        row.setUpdatedAt(now);
        deviceWsAuthDao.updateById(row);
        return next;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public String provisionNewBootstrap(String deviceIdOrMac) {
        String normalized = requireNormalized(deviceIdOrMac);
        DeviceWsAuthEntity row = selectForUpdate(normalized);
        Date now = new Date();
        String plaintext = DeviceBootstrapCrypto.generatePlaintext();
        String hash = DeviceBootstrapCrypto.hash(requireServerSecret(), plaintext);
        if (row == null) {
            row = newRow(normalized, 1L, DeviceWsAuthEntity.STATUS_ACTIVE, now);
            row.setBootstrapKeyHash(hash);
            deviceWsAuthDao.insert(row);
        } else {
            if (!DeviceWsAuthEntity.STATUS_ACTIVE.equals(row.getStatus())) {
                long next = (row.getCredentialVersion() == null ? 0L : row.getCredentialVersion()) + 1L;
                row.setCredentialVersion(next);
                row.setStatus(DeviceWsAuthEntity.STATUS_ACTIVE);
            }
            row.setBootstrapKeyHash(hash);
            row.setUpdatedAt(now);
            deviceWsAuthDao.updateById(row);
        }
        log.info("[ws_auth] bootstrap_provisioned device_id_set=true");
        return plaintext;
    }

    @Override
    public boolean verifyBootstrapKey(String deviceIdOrMac, String presentedPlaintext) {
        if (StringUtils.isBlank(presentedPlaintext)) {
            return false;
        }
        String normalized = MacAddressUtils.toTokenDeviceId(deviceIdOrMac);
        if (normalized == null) {
            String canonical = MacAddressUtils.toCanonical(deviceIdOrMac);
            normalized = MacAddressUtils.toTokenDeviceId(canonical);
        }
        if (normalized == null) {
            return false;
        }
        DeviceWsAuthEntity row = deviceWsAuthDao.selectOne(
                new QueryWrapper<DeviceWsAuthEntity>().eq("device_id", normalized));
        if (row == null || !DeviceWsAuthEntity.STATUS_ACTIVE.equals(row.getStatus())) {
            return false;
        }
        if (StringUtils.isBlank(row.getBootstrapKeyHash())) {
            return false;
        }
        try {
            return DeviceBootstrapCrypto.matches(
                    requireServerSecret(), presentedPlaintext.trim(), row.getBootstrapKeyHash());
        } catch (Exception e) {
            return false;
        }
    }

    @Override
    public DeviceWsAuthStateVO getState(String deviceIdOrMac) {
        String normalized = MacAddressUtils.toTokenDeviceId(deviceIdOrMac);
        if (normalized == null) {
            return null;
        }
        DeviceWsAuthEntity row = deviceWsAuthDao.selectOne(
                new QueryWrapper<DeviceWsAuthEntity>().eq("device_id", normalized));
        if (row == null) {
            return null;
        }
        return toVo(row);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public long markUnbound(String deviceIdOrMac) {
        return markNonActive(deviceIdOrMac, DeviceWsAuthEntity.STATUS_UNBOUND);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public long markDisabled(String deviceIdOrMac) {
        return markNonActive(deviceIdOrMac, DeviceWsAuthEntity.STATUS_DISABLED);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public long markRevoked(String deviceIdOrMac) {
        return markNonActive(deviceIdOrMac, DeviceWsAuthEntity.STATUS_DISABLED);
    }

    @Override
    public DeviceWsAuthEntity requireRow(String normalizedDeviceId) {
        DeviceWsAuthEntity row = deviceWsAuthDao.selectOne(
                new QueryWrapper<DeviceWsAuthEntity>().eq("device_id", normalizedDeviceId));
        if (row == null) {
            throw new IllegalStateException("ws auth row missing");
        }
        return row;
    }

    private long markNonActive(String deviceIdOrMac, String status) {
        String normalized = requireNormalized(deviceIdOrMac);
        DeviceWsAuthEntity row = selectForUpdate(normalized);
        Date now = new Date();
        long nowEpoch = now.getTime() / 1000L;
        long nextVersion;
        if (row == null) {
            nextVersion = 1L;
            row = newRow(normalized, nextVersion, status, now);
            row.setLegacyRevokedBeforeIat(nowEpoch);
            row.setBootstrapKeyHash(null);
            deviceWsAuthDao.insert(row);
        } else {
            nextVersion = (row.getCredentialVersion() == null ? 0L : row.getCredentialVersion()) + 1L;
            row.setCredentialVersion(nextVersion);
            row.setStatus(status);
            // 永久抬高 v1 边界；重绑不得清除
            long prev = row.getLegacyRevokedBeforeIat() == null ? 0L : row.getLegacyRevokedBeforeIat();
            row.setLegacyRevokedBeforeIat(Math.max(prev, nowEpoch));
            // 吊销后旧 bootstrap 立即失效
            row.setBootstrapKeyHash(null);
            row.setUpdatedAt(now);
            deviceWsAuthDao.updateById(row);
        }
        enqueueOutbox(normalized, nextVersion, status, now);
        // 不在此同步推送：由调用方在事务提交后 tryNotify，以便准确返回 sync_closed/pending
        log.info("[ws_auth] status_changed device_id_set=true status={} credential_version={} legacy_boundary_set=true",
                status, nextVersion);
        return nextVersion;
    }

    private void enqueueOutbox(String normalized, long version, String status, Date now) {
        DeviceWsRevokeOutboxEntity out = new DeviceWsRevokeOutboxEntity();
        out.setDeviceId(normalized);
        out.setCredentialVersion(version);
        out.setStatus(status);
        out.setAttempts(0);
        out.setNextAttemptAt(now);
        out.setCreatedAt(now);
        revokeOutboxDao.insert(out);
    }

    private DeviceWsAuthEntity selectForUpdate(String normalized) {
        return deviceWsAuthDao.selectOne(
                new QueryWrapper<DeviceWsAuthEntity>()
                        .eq("device_id", normalized)
                        .last("FOR UPDATE"));
    }

    private static DeviceWsAuthEntity newRow(String normalized, long version, String status, Date now) {
        DeviceWsAuthEntity row = new DeviceWsAuthEntity();
        row.setDeviceId(normalized);
        row.setCredentialVersion(version);
        row.setStatus(status);
        row.setCreatedAt(now);
        row.setUpdatedAt(now);
        return row;
    }

    private String requireServerSecret() {
        String secret = sysParamsService.getValue(Constant.SERVER_SECRET, true);
        if (StringUtils.isBlank(secret) || "null".equals(secret)) {
            throw new IllegalStateException("server secret not configured");
        }
        return secret;
    }

    private static String requireNormalized(String deviceIdOrMac) {
        String normalized = MacAddressUtils.toTokenDeviceId(deviceIdOrMac);
        if (normalized == null) {
            String canonical = MacAddressUtils.toCanonical(deviceIdOrMac);
            normalized = MacAddressUtils.toTokenDeviceId(canonical);
        }
        if (normalized == null) {
            throw new IllegalArgumentException("invalid device id");
        }
        return normalized;
    }

    private static DeviceWsAuthStateVO toVo(DeviceWsAuthEntity row) {
        DeviceWsAuthStateVO vo = new DeviceWsAuthStateVO();
        vo.setDeviceId(row.getDeviceId());
        vo.setCredentialVersion(row.getCredentialVersion());
        vo.setStatus(row.getStatus());
        vo.setLegacyRevokedBeforeIat(row.getLegacyRevokedBeforeIat());
        vo.setBootstrapConfigured(StringUtils.isNotBlank(row.getBootstrapKeyHash()));
        if (row.getUpdatedAt() != null) {
            vo.setUpdatedAtEpochSec(row.getUpdatedAt().getTime() / 1000L);
        }
        return vo;
    }
}
