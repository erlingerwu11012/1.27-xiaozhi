package xiaozhi.modules.rolepack.config;

import java.util.ArrayList;
import java.util.List;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import lombok.Data;

/**
 * 视觉角色包配置。私钥优先从环境变量 ROLE_PACK_SIGNING_PRIVATE_KEY_PEM 注入。
 * 下载基地址优先从 ROLE_PACK_DOWNLOAD_BASE_URL 注入。
 * 期望公钥指纹优先从 ROLE_PACK_EXPECTED_PUBLIC_KEY_SHA256 注入。
 */
@Data
@Component
@ConfigurationProperties(prefix = "xiaozhi.role-pack")
public class RolePackProperties {

    /** 角色包根目录（相对或绝对），与 uploads/emoji/firmware 隔离 */
    private String storageDir = "rolepacks";

    /** 发布时写入的默认最低固件；不由上传表单填写 */
    private String defaultMinFw = "1.0.0";

    /** 发布时写入的默认支持型号；不由上传表单填写 */
    private List<String> defaultSupportedBoards = new ArrayList<>(List.of("esp-box-3"));

    /**
     * 下载 URL 前缀，如 https://cdn.xiaozhi.me/xiaozhi。
     * 不得使用 official-host 占位；须由环境变量/部署配置提供。
     */
    private String downloadBaseUrl = "";

    /** ECDSA P-256 私钥 PEM（PKCS#8）。生产环境与联调均必填。 */
    private String signingPrivateKeyPem = "";

    /** 私钥文件路径（可选，优先于 pem 字符串） */
    private String signingPrivateKeyPath = "";

    /**
     * 期望公钥 SHA-256 指纹（hex，小写，对 X.509 SubjectPublicKeyInfo DER 计算）。
     * 须与当前固件内置 ES256 公钥一致；不一致时 fail-closed。
     */
    private String expectedPublicKeySha256 = "";

    /** 短时下载令牌 TTL（秒） */
    private long downloadTokenTtlSeconds = 900;

    /** 单令牌最大下载次数（允许网络中断重试；用尽后任务可重连重签，不永久锁死） */
    private int downloadMaxCount = 10;

    /** 推送到 xiaozhi-server 的 URL */
    private String pushUrl = "http://127.0.0.1:8006/api/v1/device/send";

    /** 任务超时（分钟），超时标记 expired */
    private int taskTimeoutMinutes = 60;

    /** 可重试错误最大重试次数（ACK failed 后回队） */
    private int maxRetryCount = 3;

    /**
     * update_spine 最大自动投递次数（含首次 deploy 推送与重连重投）。
     * 达到后标记 needs_manual_review，停止自动投递。
     */
    private int maxRedeliverAttempts = 3;

    /**
     * 重连重投指数退避基准（毫秒）。
     * 已投递 1 次后需等待 base；2 次后 2*base；3 次后 4*base …
     */
    private long redeliverBackoffBaseMs = 30_000L;

    /** progress 写库最小间隔（毫秒） */
    private long progressWriteMinIntervalMs = 1000;

    /** progress 写库最小变化百分比（与时间阈值同时满足才写；终态立即写） */
    private int progressWriteMinDeltaPercent = 5;
}
