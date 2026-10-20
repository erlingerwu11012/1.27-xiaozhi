package xiaozhi.modules.face.config;

import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;

/**
 * Face 代理启动安全门禁（与 spring.profiles 无关）。
 *
 * <ul>
 *   <li>JWT secret 必须存在（除非显式 allow-insecure=true，仅本机实验）</li>
 *   <li>静态 account-id 已废弃：空或 default 均可启动，运行时用 SecurityUser.getUserId()</li>
 *   <li>禁止用 default/占位值绕过租户隔离</li>
 * </ul>
 */
@Slf4j
@Component
@Order(20)
@RequiredArgsConstructor
public class FaceSecurityStartupValidator implements ApplicationRunner {

    private final FaceProperties faceProperties;

    @Value("${spring.profiles.active:prod}")
    private String activeProfile;

    @Override
    public void run(ApplicationArguments args) {
        // allow-insecure 是唯一显式旁路；不得因 profile=dev 跳过 JWT 门禁
        if (faceProperties.isAllowInsecure()) {
            log.warn(
                    "xiaozhi.face.allow-insecure=true：跳过 JWT 启动门禁"
                            + "（profile={}）；生产部署严禁开启",
                    activeProfile);
            logIgnoredStaticAccountId();
            return;
        }
        if (StringUtils.isBlank(faceProperties.getJwtSecret())) {
            throw new IllegalStateException(
                    "FACE_JWT_SECRET / xiaozhi.face.jwt-secret 未配置："
                            + "已 fail-closed（与 profile 无关）。"
                            + "请与 face-api 使用同一服务间密钥。");
        }
        logIgnoredStaticAccountId();
        log.info(
                "face proxy security check ok (profile={}, account_id=runtime_user_id, jwt=set)",
                activeProfile);
    }

    private void logIgnoredStaticAccountId() {
        String staticAccountId = faceProperties.getAccountId();
        if (StringUtils.isBlank(staticAccountId)) {
            return;
        }
        if ("default".equalsIgnoreCase(staticAccountId.trim())
                || FaceAccountIdRules.isReserved(staticAccountId)) {
            log.warn(
                    "xiaozhi.face.account-id={} 已忽略；"
                            + "face JWT account_id 使用 SecurityUser.getUserId()",
                    staticAccountId.trim().equalsIgnoreCase("default")
                            ? "default"
                            : "reserved");
        } else {
            log.warn(
                    "xiaozhi.face.account-id 已废弃且将被忽略；"
                            + "face JWT account_id 使用 SecurityUser.getUserId()");
        }
    }

    /**
     * 保留供兼容性清单/文档引用；启动门禁不再依赖此判定。
     *
     * @deprecated 安全规则已改为 profile-independent
     */
    @Deprecated
    public static boolean isProdLike(String profile) {
        if (profile == null || profile.isBlank()) {
            return true;
        }
        String p = profile.toLowerCase();
        return !(p.contains("dev") || p.contains("test"));
    }
}
