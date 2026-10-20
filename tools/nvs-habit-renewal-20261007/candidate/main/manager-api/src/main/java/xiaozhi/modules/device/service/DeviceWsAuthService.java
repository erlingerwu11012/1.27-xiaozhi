package xiaozhi.modules.device.service;

import xiaozhi.modules.device.entity.DeviceWsAuthEntity;
import xiaozhi.modules.device.vo.DeviceWsAuthStateVO;

/**
 * 设备 WSS 鉴权状态：bootstrap 密钥、credential_version、legacy v1 边界。
 */
public interface DeviceWsAuthService {

    /**
     * 确保 active；若无记录则创建 version=1；若曾 unbound/disabled 则 version++ 并恢复 active。
     * 不轮转 bootstrap（除非缺失则生成并返回明文一次）。
     * 返回签发用的 credential_version。
     */
    long ensureActiveForIssue(String deviceIdOrMac);

    /**
     * 绑定/重绑：确保 active，并生成新的 bootstrap 明文（旧密钥立即失效）。
     * 返回明文仅供调用方一次性下发/写入 redeem；库中只存哈希。
     */
    String provisionNewBootstrap(String deviceIdOrMac);

    /** 常量时间校验 bootstrap 明文是否匹配该 device。 */
    boolean verifyBootstrapKey(String deviceIdOrMac, String presentedPlaintext);

    /** 按规范化或原始 MAC 查询状态；不存在返回 null（调用方 fail-closed）。 */
    DeviceWsAuthStateVO getState(String deviceIdOrMac);

    /**
     * 解绑：同一事务内 status=unbound、version++、写入 legacy_revoked_before_iat、revoke outbox。
     */
    long markUnbound(String deviceIdOrMac);

    /** 禁用：status=disabled、version++、legacy 边界、outbox。 */
    long markDisabled(String deviceIdOrMac);

    /** 显式吊销：与 disabled 相同语义。 */
    long markRevoked(String deviceIdOrMac);

    DeviceWsAuthEntity requireRow(String normalizedDeviceId);
}
