package xiaozhi.modules.pay.service;

import xiaozhi.modules.pay.vo.OneApiDeviceTokenVO;

/**
 * one-api 设备 token 解析服务（阶段1B：设备按 sys_user 路由 token）。
 */
public interface OneApiBindingService {

    /**
     * 根据主系统用户ID解析该用户绑定的 one-api 设备 token。
     * fail-closed：未绑定 / 密文为空 / 密钥未配置 / 解密失败均抛出明确异常，绝不返回默认 token。
     *
     * @param sysUserId 主系统用户ID（sys_user.id）
     * @return 解密后的设备 token 信息
     */
    OneApiDeviceTokenVO resolveDeviceToken(Long sysUserId);
}
