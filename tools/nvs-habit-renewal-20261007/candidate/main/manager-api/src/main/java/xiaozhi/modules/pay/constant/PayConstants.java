package xiaozhi.modules.pay.constant;

import cn.hutool.core.util.IdUtil;

/**
 * 支付模块常量
 */
public final class PayConstants {

    private PayConstants() {
    }

    /** 支付渠道：mock（阶段1内部测试） */
    public static final String CHANNEL_MOCK = "mock";
    /** 支付渠道：微信（预留） */
    public static final String CHANNEL_WECHAT = "wechat";
    /** 支付渠道：支付宝（预留） */
    public static final String CHANNEL_ALIPAY = "alipay";

    /** 订单状态：待支付 */
    public static final String STATUS_PENDING = "pending";
    /** 订单状态：已支付 */
    public static final String STATUS_PAID = "paid";
    /** 订单状态：已发货（额度已发放） */
    public static final String STATUS_DELIVERED = "delivered";
    /** 订单状态：已关闭 */
    public static final String STATUS_CLOSED = "closed";
    /** 订单状态：已退款 */
    public static final String STATUS_REFUNDED = "refunded";
    /** 订单状态：失败 */
    public static final String STATUS_FAILED = "failed";

    /** 额度变更类型：充值发放 */
    public static final String CHANGE_TYPE_RECHARGE = "recharge";
    /** 额度变更类型：消费扣减 */
    public static final String CHANGE_TYPE_CONSUME = "consume";
    /** 额度变更类型：退款扣减 */
    public static final String CHANGE_TYPE_REFUND = "refund";

    /** 未配置支付渠道时的统一错误信息 */
    public static final String MSG_CHANNEL_NOT_CONFIGURED = "支付渠道尚未配置";

    /** mock 支付已关闭 */
    public static final String MSG_MOCK_DISABLED = "mock 支付已关闭";

    /** 支付宝未配置（缺少密钥/参数） */
    public static final String MSG_ALIPAY_NOT_CONFIGURED = "支付宝支付尚未配置";

    /** 额度换算：1 点 = 500 one-api quota（阶段1固定，后续再配置化） */
    public static final long ONEAPI_QUOTA_PER_POINT = 500L;

    /** 点数展示精度（小数位） */
    public static final int POINTS_SCALE = 3;

    /** 账单/用量统计统一时区（自然日按中国标准时间切分，避免 MySQL 会话时区与 JVM 默认时区混用） */
    public static final String BILLING_ZONE_ID = "Asia/Shanghai";

    /** Asia/Shanghai 相对 UTC 的固定偏移秒数（中国自 1991 年起无夏令时，账单区间用固定偏移换算 epoch 自然日） */
    public static final long BILLING_ZONE_OFFSET_SECONDS = 8 * 3600L;

    /** 余额来源：one-api 实时快照 */
    public static final String BALANCE_SOURCE_ONEAPI = "oneapi";
    /** 余额来源：本地缓存（one-api 快照不可读时的降级展示） */
    public static final String BALANCE_SOURCE_CACHE = "cache";
    /** 余额来源：无（无额度记录） */
    public static final String BALANCE_SOURCE_NONE = "none";

    /** 消费日志不可用原因：当前用户未绑定 one-api 账户 */
    public static final String CONSUME_REASON_NO_BINDING = "no_binding";
    /** 消费日志不可用原因：one-api 运行时关闭了消费日志记录 */
    public static final String CONSUME_REASON_LOGS_DISABLED = "logs_disabled";
    /** 消费日志不可用原因：one-api 日志库不可读 */
    public static final String CONSUME_REASON_LOGS_UNREADABLE = "logs_unreadable";

    /** one-api 充值状态：待处理 */
    public static final String ONEAPI_RECHARGE_PENDING = "pending";
    /** one-api 充值状态：成功 */
    public static final String ONEAPI_RECHARGE_SUCCESS = "success";
    /** one-api 充值状态：失败 */
    public static final String ONEAPI_RECHARGE_FAILED = "failed";

    /** one-api 充值流水状态：成功 */
    public static final String RECHARGE_LOG_SUCCESS = "success";
    /** one-api 充值流水状态：失败 */
    public static final String RECHARGE_LOG_FAILED = "failed";

    /** one-api 用户未绑定错误信息 */
    public static final String MSG_ONEAPI_BINDING_NOT_FOUND = "one-api 用户未绑定";
    /** one-api admin token 未配置错误信息 */
    public static final String MSG_ONEAPI_ADMIN_TOKEN_NOT_CONFIGURED = "one-api admin token 未配置";
    /** one-api 设备 token 未配置（绑定存在但 token 密文为空） */
    public static final String MSG_ONEAPI_DEVICE_TOKEN_NOT_CONFIGURED = "one-api 设备 token 未配置";
    /** one-api 设备 token 加密密钥未配置 */
    public static final String MSG_ONEAPI_TOKEN_CIPHER_KEY_NOT_CONFIGURED = "one-api 设备 token 加密密钥未配置";
    /** 内部服务间密钥未配置 */
    public static final String MSG_ONEAPI_INTERNAL_TOKEN_NOT_CONFIGURED = "one-api 服务间密钥未配置";
    /** 内部服务间密钥无效 */
    public static final String MSG_ONEAPI_INTERNAL_TOKEN_INVALID = "无效的服务间密钥";

    /** one-api 计费账户开通失败 */
    public static final String MSG_ONEAPI_PROVISION_FAILED = "one-api 计费账户开通失败";

    /** one-api 用户名前缀（保证全局唯一，可追溯 sysUserId） */
    public static final String ONEAPI_USERNAME_PREFIX = "realecho_";

    /** 设备专用 token 名称 */
    public static final String ONEAPI_DEVICE_TOKEN_NAME = "xiaozhi-device";

    /** 设备专用 token 允许使用的模型列表（与设备网关 LLM/ASR/TTS 对齐） */
    public static final String ONEAPI_DEVICE_TOKEN_MODELS =
            "qwen-audio-3.0-tts-plus,qwen3-asr-flash-realtime,aimi-chat,deepseek-chat,FunAudioLLM/CosyVoice2-0.5B,FunAudioLLM/SenseVoiceSmall,Qwen/Qwen3-VL-8B-Instruct,memory";

    /** one-api topup 备注前缀 */
    public static final String ONEAPI_RECHARGE_REMARK_PREFIX = "realecho_recharge:";

    /**
     * 生成全局唯一商户订单号
     */
    public static String generateOutTradeNo() {
        return "RE" + IdUtil.getSnowflakeNextIdStr();
    }
}
