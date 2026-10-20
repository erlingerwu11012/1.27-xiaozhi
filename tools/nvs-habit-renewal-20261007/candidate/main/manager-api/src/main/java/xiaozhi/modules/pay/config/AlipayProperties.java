package xiaozhi.modules.pay.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import lombok.Data;

/**
 * 支付宝电脑网站支付配置。
 *
 * 机密（应用私钥 / 支付宝公钥）只存「文件路径」，运行时由 AlipayServiceImpl 读取 PEM 内容进内存，
 * 全程不打印；其余为普通配置。全部由环境变量注入，禁止硬编码。
 */
@Data
@Component
@ConfigurationProperties(prefix = "xiaozhi.pay.alipay")
public class AlipayProperties {

    /** 应用 ID。注入：ALIPAY_APP_ID */
    private String appId = "";

    /** 网关地址。注入：ALIPAY_GATEWAY */
    private String gateway = "https://openapi.alipay.com/gateway.do";

    /** 签名算法。注入：ALIPAY_SIGN_TYPE */
    private String signType = "RSA2";

    /** 应用私钥文件路径。注入：ALIPAY_PRIVATE_KEY_PATH */
    private String privateKeyPath = "/etc/realecho/pay/alipay/app_private_key.pem";

    /** 支付宝公钥文件路径。注入：ALIPAY_PUBLIC_KEY_PATH */
    private String publicKeyPath = "/etc/realecho/pay/alipay/alipay_public_key.pem";

    /** 异步通知地址。注入：ALIPAY_NOTIFY_URL */
    private String notifyUrl = "";

    /** 同步跳转地址（前端直达）。注入：ALIPAY_RETURN_URL */
    private String returnUrl = "";

    /** 字符集。注入：ALIPAY_CHARSET */
    private String charset = "utf-8";

    /** 报文格式。注入：ALIPAY_FORMAT */
    private String format = "json";

    /** 销售产品码：电脑网站支付固定值。注入：ALIPAY_PRODUCT_CODE */
    private String productCode = "FAST_INSTANT_TRADE_PAY";

    /** 连接超时（毫秒） */
    private int connectTimeoutMs = 10000;

    /** 读取超时（毫秒） */
    private int readTimeoutMs = 15000;
}
