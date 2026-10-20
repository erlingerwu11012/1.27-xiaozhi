package xiaozhi.modules.pay.service;

import xiaozhi.modules.pay.vo.PayOrderVO;

/**
 * 支付发货服务：支付成功（paid）后，执行 one-api 充值（topup）并置为 delivered。
 *
 * 支付宝 / mock / 未来微信等所有渠道共用这一套发货逻辑，保证幂等：
 * 重复回调/重复通知不会重复充值 one-api。
 */
public interface PaymentDeliveryService {

    /**
     * 将指定订单从支付成功状态推进到发货（delivered）。
     *
     * @param orderNo 商户订单号
     * @param tradeNo 第三方交易号（mock 为 MOCK_订单号，支付宝为支付宝交易号）
     * @return 最新订单状态
     */
    PayOrderVO deliver(String orderNo, String tradeNo);
}
