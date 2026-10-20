package xiaozhi.modules.pay.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import lombok.Data;

/**
 * 支付模块顶层配置。
 */
@Data
@Component
@ConfigurationProperties(prefix = "xiaozhi.pay")
public class PayProperties {

    /** mock 支付开关：默认 false（生产关闭），仅显式开启或测试环境可用。注入：MOCK_PAY_ENABLED */
    private boolean mockEnabled = false;
}
