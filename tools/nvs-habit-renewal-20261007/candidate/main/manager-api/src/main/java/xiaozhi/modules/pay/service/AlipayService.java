package xiaozhi.modules.pay.service;

import xiaozhi.modules.pay.entity.PayOrderEntity;

/**
 * 支付宝 Service（支付宝电脑网站支付）
 */
public interface AlipayService {

    /**
     * 是否已配置真实支付宝参数（appId + 私钥 + 支付宝公钥文件均就绪）
     */
    boolean isConfigured();

    /**
     * 创建支付宝电脑网站支付表单（alipay.trade.page.pay）。
     *
     * @param order 已落库的 pending 订单
     * @return 自动提交的支付表单 HTML（含 &lt;form&gt; + &lt;script&gt; 自动跳转）
     */
    String createPagePay(PayOrderEntity order);

    /**
     * 校验支付宝异步通知签名（RSA2）。验签失败返回 false。
     *
     * @param params 支付宝 POST 的 form 参数（含 sign / sign_type）
     */
    boolean verifyNotifySign(java.util.Map<String, String> params);
}
