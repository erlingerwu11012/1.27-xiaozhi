package xiaozhi.modules.officialtts.engine;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

/**
 * Fail-closed isolation profile: never fall back to production JDBC, Redis or gateway.
 */
@Component
@Profile("iso")
public class OfficialTtsIsolationGuard implements ApplicationRunner {
    private final Environment env;

    public OfficialTtsIsolationGuard(Environment env) {
        this.env = env;
    }

    @Override
    public void run(ApplicationArguments args) {
        String jdbc = first(
                env.getProperty("spring.datasource.druid.url"),
                env.getProperty("spring.datasource.url"));
        String redisHost = env.getProperty("spring.data.redis.host");
        String redisPort = env.getProperty("spring.data.redis.port");
        String gateway = env.getProperty("official.tts.gateway.base");
        if (jdbc == null || !jdbc.contains("official_tts_iso_manager") || !jdbc.contains("3307")
                || !jdbc.contains("127.0.0.1")) {
            throw new IllegalStateException("iso_jdbc_must_be_official_tts_iso_manager_3307");
        }
        if (jdbc.contains("xiaozhi_esp32_server") || jdbc.contains(":3306/")) {
            throw new IllegalStateException("iso_jdbc_must_not_use_production");
        }
        if (!"127.0.0.1".equals(redisHost) || !"6380".equals(String.valueOf(redisPort))) {
            throw new IllegalStateException("iso_redis_must_be_127.0.0.1_6380");
        }
        if (gateway == null || !(gateway.contains("127.0.0.1:13011") || gateway.contains("127.0.0.1:13012"))) {
            throw new IllegalStateException("iso_gateway_must_be_13011");
        }
        if (gateway.contains(":3011") && !gateway.contains(":13011") && !gateway.contains(":13012")) {
            throw new IllegalStateException("iso_gateway_must_not_use_production");
        }
        String smsKey = env.getProperty("aliyun.sms.access_key_id");
        if (smsKey != null && !smsKey.isBlank()) {
            throw new IllegalStateException("iso_must_not_configure_real_sms");
        }
    }

    private static String first(String a, String b) {
        return a != null && !a.isBlank() ? a : b;
    }
}
