package xiaozhi.modules.face.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import lombok.Data;

/**
 * face-api 代理配置。密钥仅从环境变量 / 部署配置注入，禁止硬编码。
 */
@Data
@Component
@ConfigurationProperties(prefix = "xiaozhi.face")
public class FaceProperties {

    /** face-api 根地址，例如 http://127.0.0.1:8765 */
    private String baseUrl = "http://127.0.0.1:8765";

    /**
     * 与 face-api FACE_JWT_SECRET 相同；空则启动/代理 fail-closed（与 profile 无关）。
     * 注入：FACE_JWT_SECRET 或 xiaozhi.face.jwt-secret
     */
    private String jwtSecret = "";

    /** @deprecated 已废弃；运行时 account_id = SecurityUser.getUserId()。勿再依赖本字段。 */
    @Deprecated
    private String accountId = "";

    /**
     * 显式旁路：允许无 JWT 启动/代理。默认 false。
     * 生产严禁开启；不得用 spring.profiles=dev 代替本开关。
     */
    private boolean allowInsecure = false;

    private int connectTimeoutMs = 5000;

    private int readTimeoutMs = 30000;
}
