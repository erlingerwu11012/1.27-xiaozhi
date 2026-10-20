package xiaozhi.modules.pay.service;

/**
 * one-api 计费账户开通服务（阶段1C）。
 */
public interface OneApiProvisioningService {

    /**
     * 幂等确保主系统用户已开通 one-api 计费账户（user + 设备 token + 绑定）。
     * 已完整绑定则直接返回；未绑定则创建，失败不留半绑定。
     *
     * @param sysUserId 主系统用户ID（sys_user.id）
     */
    void ensureProvisioned(Long sysUserId);
}
