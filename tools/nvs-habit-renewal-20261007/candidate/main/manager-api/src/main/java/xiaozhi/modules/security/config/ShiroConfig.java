package xiaozhi.modules.security.config;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

import org.apache.shiro.mgt.SecurityManager;
import org.apache.shiro.session.mgt.SessionManager;
import org.apache.shiro.spring.LifecycleBeanPostProcessor;
import org.apache.shiro.spring.security.interceptor.AuthorizationAttributeSourceAdvisor;
import org.apache.shiro.spring.web.ShiroFilterFactoryBean;
import org.apache.shiro.web.config.ShiroFilterConfiguration;
import org.apache.shiro.web.mgt.DefaultWebSecurityManager;
import org.apache.shiro.web.session.mgt.DefaultWebSessionManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import jakarta.servlet.Filter;
import xiaozhi.modules.security.oauth2.Oauth2Filter;
import xiaozhi.modules.security.oauth2.Oauth2Realm;
import xiaozhi.modules.security.secret.ServerSecretFilter;
import xiaozhi.modules.sys.service.SysParamsService;

/**
 * Shiro的配置文件
 * Copyright (c) 人人开源 All rights reserved.
 * Website: https://www.renren.io
 */
@Configuration
public class ShiroConfig {

    @Bean
    public DefaultWebSessionManager sessionManager() {
        DefaultWebSessionManager sessionManager = new DefaultWebSessionManager();
        sessionManager.setSessionValidationSchedulerEnabled(false);
        sessionManager.setSessionIdUrlRewritingEnabled(false);

        return sessionManager;
    }

    @Bean("securityManager")
    public SecurityManager securityManager(Oauth2Realm oAuth2Realm, SessionManager sessionManager) {
        DefaultWebSecurityManager securityManager = new DefaultWebSecurityManager();
        securityManager.setRealm(oAuth2Realm);
        securityManager.setSessionManager(sessionManager);
        securityManager.setRememberMeManager(null);
        return securityManager;
    }

    @Bean("shiroFilter")
    public ShiroFilterFactoryBean shirFilter(SecurityManager securityManager, SysParamsService sysParamsService) {
        ShiroFilterConfiguration config = new ShiroFilterConfiguration();
        config.setFilterOncePerRequest(true);

        ShiroFilterFactoryBean shiroFilter = new ShiroFilterFactoryBean();
        shiroFilter.setSecurityManager(securityManager);
        shiroFilter.setShiroFilterConfiguration(config);

        Map<String, Filter> filters = new HashMap<>();
        // oauth过滤
        filters.put("oauth2", new Oauth2Filter());
        // 服务密钥过滤
        filters.put("server", new ServerSecretFilter(sysParamsService));
        shiroFilter.setFilters(filters);

        // 添加Shiro的内置过滤器
        /*
         * anon：无需认证就可以访问
         * authc：必须认证了才能让问
         * user：必须拥有，记住我功能，才能访问
         * perms：拥有对某个资源的权限才能访问
         * role：拥有某个角色权限才能访问
         */
        Map<String, String> filterMap = new LinkedHashMap<>();
        filterMap.put("/xiaozhi/ota/**", "anon");
        filterMap.put("/ota/**", "anon");
        filterMap.put("/otaMag/download/**", "anon");
        // 内部服务间接口：控制器自行校验 X-Realecho-Internal-Token
        filterMap.put("/official-tts/internal/media/**", "anon");
        // 视觉角色包：短时 token 下载（设备侧无 oauth2）
        filterMap.put("/role-packs/download/**", "anon");
        // 已发布角色的封面/演示视频：供 <img>/<video> 播放，控制器内校验 published
        filterMap.put("/role-packs/*/preview-image", "anon");
        filterMap.put("/role-packs/*/preview-video", "anon");
        // 视觉角色包：设备 ACK / pending（服务间密钥）
        filterMap.put("/role-packs/device/**", "server");
        filterMap.put("/wallpaper-packs/download/**", "anon");
        filterMap.put("/wallpaper-packs/*/preview-image", "anon");
        filterMap.put("/wallpaper-packs/*/preview-video", "anon");
        filterMap.put("/wallpaper-packs/device/**", "server");
        filterMap.put("/webjars/**", "anon");
        filterMap.put("/druid/**", "anon");
        filterMap.put("/v3/api-docs/**", "anon");
        filterMap.put("/doc.html", "anon");
        filterMap.put("/favicon.ico", "anon");
        filterMap.put("/user/captcha", "anon");
        filterMap.put("/user/smsVerification", "anon");
        filterMap.put("/user/login", "anon");
        filterMap.put("/user/pub-config", "anon");
        filterMap.put("/user/register", "anon");
        filterMap.put("/user/retrieve-password", "anon");
        // POST /config/server-base 供 Python 服务初始化 MQTT，需匿名访问
        filterMap.put("/config/server-base", "anon");
        // 支付宝异步通知：验签在控制器内自行完成，需匿名访问
        filterMap.put("/pay/alipay/notify", "anon");
        // 其他 config 路径使用 server 服务过滤器（需 Bearer token）
        filterMap.put("/config/**", "server");
        filterMap.put("/agent/chat-history/report", "server");
        filterMap.put("/agent/chat-history/download/**", "anon");
        filterMap.put("/agent/saveMemory/**", "server");
        // PUT /device/update 供 Python 服务更新设备配置
        filterMap.put("/device/update", "server");
        // GET /device/by-mac/** 供 Python 服务按 MAC 查询设备配置（userId 等）
        filterMap.put("/device/by-mac/**", "server");
        // xiaozhi-server 读取账号范围统一用户目录（服务密钥；不得走网页 OAuth 会话）
        filterMap.put("/user-identities/device-directory/**", "server");
        filterMap.put("/user-identities/internal/**", "server");
        filterMap.put("/person-memory/internal/**", "server");
        filterMap.put("/habits/internal/**", "server");
        // 设备 WSS auth state 查询 / 禁用（服务间 Bearer server.secret）
        filterMap.put("/device/ws-auth/**", "server");
        filterMap.put("/agent/play/**", "anon");
        filterMap.put("/**", "oauth2");
        shiroFilter.setFilterChainDefinitionMap(filterMap);

        return shiroFilter;
    }

    @Bean("lifecycleBeanPostProcessor")
    public LifecycleBeanPostProcessor lifecycleBeanPostProcessor() {
        return new LifecycleBeanPostProcessor();
    }

    @Bean
    public AuthorizationAttributeSourceAdvisor authorizationAttributeSourceAdvisor(SecurityManager securityManager) {
        AuthorizationAttributeSourceAdvisor advisor = new AuthorizationAttributeSourceAdvisor();
        advisor.setSecurityManager(securityManager);
        return advisor;
    }
}
