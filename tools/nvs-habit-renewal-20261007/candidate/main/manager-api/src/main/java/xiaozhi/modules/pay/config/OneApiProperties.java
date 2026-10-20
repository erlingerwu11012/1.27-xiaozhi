package xiaozhi.modules.pay.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import lombok.Data;

/**
 * one-api 充值客户端配置。admin token / 加密密钥 / 服务间密钥仅从环境变量注入，禁止硬编码。
 */
@Data
@Component
@ConfigurationProperties(prefix = "xiaozhi.pay.oneapi")
public class OneApiProperties {

    /** one-api 根地址 */
    private String baseUrl = "http://127.0.0.1:3000";

    /** one-api 管理员 token；空则 topup fail-closed。注入：ONEAPI_ADMIN_TOKEN */
    private String adminToken = "";

    /** one-api 设备 token 加密密钥（64 字符 hex）。注入：ONEAPI_TOKEN_CIPHER_KEY */
    private String tokenCipherKey = "";

    /** 服务间调用密钥。注入：ONEAPI_INTERNAL_TOKEN */
    private String internalToken = "";

    /** 注册送体验额度（one-api quota，默认 0 不赠送）。注入：ONEAPI_REGISTER_TRIAL_QUOTA */
    private long registerTrialQuota = 0;

    /** 连接超时（毫秒） */
    private int connectTimeoutMs = 3000;

    /** 读取超时（毫秒） */
    private int readTimeoutMs = 10000;
}
