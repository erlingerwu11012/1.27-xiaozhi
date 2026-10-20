package xiaozhi.modules.pay.service;

import xiaozhi.modules.pay.vo.PayOrderVO;

/**
 * Mock 支付 Service（仅测试/管理员场景；生产默认关闭）
 */
public interface MockPayService {

    /**
     * mock 支付是否开启（配置开关，默认关闭）
     */
    boolean isEnabled();

    /**
     * 模拟支付成功（幂等）：仅能操作当前用户自己的订单。
     */
    PayOrderVO mockNotify(Long userId, String orderNo);
}
