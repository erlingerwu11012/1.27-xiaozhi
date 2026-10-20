package xiaozhi.modules.pay.service;

/**
 * 微信支付 Service（阶段1占位，未接入真实微信支付 API v3）
 */
public interface WechatPayService {

    /**
     * 是否已配置真实微信支付参数（阶段1恒为 false）
     */
    boolean isConfigured();

    /**
     * 创建微信 Native 支付订单（占位，未接入真实 API）
     *
     * @param orderId 内部订单ID
     * @return 支付二维码等支付参数（阶段1未实现）
     */
    Object createNativeOrder(Long orderId);
}
