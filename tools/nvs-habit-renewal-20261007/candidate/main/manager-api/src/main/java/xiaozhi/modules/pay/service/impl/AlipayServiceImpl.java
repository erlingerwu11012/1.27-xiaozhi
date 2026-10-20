package xiaozhi.modules.pay.service.impl;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;

import com.alipay.api.AlipayClient;
import com.alipay.api.DefaultAlipayClient;
import com.alipay.api.internal.util.AlipaySignature;
import com.alipay.api.request.AlipayTradePagePayRequest;
import com.alipay.api.response.AlipayTradePagePayResponse;

import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.pay.config.AlipayProperties;
import xiaozhi.modules.pay.constant.PayConstants;
import xiaozhi.modules.pay.entity.PayOrderEntity;
import xiaozhi.modules.pay.service.AlipayService;

/**
 * 支付宝电脑网站支付实现（alipay.trade.page.pay）。
 *
 * 安全约定：
 * - 应用私钥 / 支付宝公钥从 PEM 文件读取进内存，全程不打印、不入日志；
 * - 金额以本地 pay_order.amount_cents 为准，换算为元并保留两位小数；
 * - out_trade_no / subject 均取自本地订单，不信任外部输入。
 */
@Slf4j
@Service
public class AlipayServiceImpl implements AlipayService {

    private final AlipayProperties properties;

    public AlipayServiceImpl(AlipayProperties properties) {
        this.properties = properties;
    }

    @Override
    public boolean isConfigured() {
        if (StringUtils.isBlank(properties.getAppId())) {
            return false;
        }
        if (StringUtils.isBlank(properties.getNotifyUrl())) {
            return false;
        }
        return fileExists(properties.getPrivateKeyPath()) && fileExists(properties.getPublicKeyPath());
    }

    @Override
    public String createPagePay(PayOrderEntity order) {
        if (!isConfigured()) {
            throw new RenException(PayConstants.MSG_ALIPAY_NOT_CONFIGURED);
        }

        String privateKey = readKey(properties.getPrivateKeyPath());
        String alipayPublicKey = readKey(properties.getPublicKeyPath());

        AlipayClient client = new DefaultAlipayClient(
                properties.getGateway(),
                properties.getAppId(),
                privateKey,
                properties.getFormat(),
                properties.getCharset(),
                alipayPublicKey,
                properties.getSignType());

        AlipayTradePagePayRequest request = new AlipayTradePagePayRequest();
        request.setNotifyUrl(properties.getNotifyUrl());
        request.setReturnUrl(properties.getReturnUrl());

        // total_amount 以本地订单金额为准：分 -> 元，保留两位小数
        BigDecimal amount = BigDecimal.valueOf(order.getAmountCents())
                .divide(BigDecimal.valueOf(100), 2, RoundingMode.HALF_UP);

        request.setBizContent("{\"out_trade_no\":\"" + order.getOutTradeNo() + "\","
                + "\"product_code\":\"" + properties.getProductCode() + "\","
                + "\"total_amount\":" + amount.toPlainString() + ","
                + "\"subject\":\"" + escapeJson(order.getPackageName()) + "\"}");

        try {
            AlipayTradePagePayResponse response = client.pageExecute(request);
            if (!response.isSuccess()) {
                log.error("支付宝下单失败: outTradeNo={}, code={}, subCode={}, msg={}",
                        order.getOutTradeNo(),
                        response.getCode(),
                        response.getSubCode(),
                        response.getMsg());
                throw new RenException("支付宝下单失败: " + abbreviate(response.getMsg()));
            }
            // response.getBody() 为可直接渲染的自动提交表单 HTML
            return response.getBody();
        } catch (RenException e) {
            throw e;
        } catch (Exception e) {
            log.error("支付宝下单异常: outTradeNo={}, err={}", order.getOutTradeNo(), e.getMessage());
            throw new RenException("支付宝下单异常: " + abbreviate(e.getMessage()));
        }
    }

    @Override
    public boolean verifyNotifySign(java.util.Map<String, String> params) {
        if (!isConfigured()) {
            return false;
        }
        String alipayPublicKey = readKey(properties.getPublicKeyPath());
        try {
            return AlipaySignature.rsaCheckV1(params, alipayPublicKey,
                    properties.getCharset(), properties.getSignType());
        } catch (Exception e) {
            log.error("支付宝异步通知验签异常: {}", e.getMessage());
            return false;
        }
    }

    private boolean fileExists(String path) {
        if (StringUtils.isBlank(path)) {
            return false;
        }
        return Files.isRegularFile(Path.of(path));
    }

    private String readKey(String path) {
        try {
            String pem = Files.readString(Path.of(path), StandardCharsets.UTF_8);
            return stripPem(pem);
        } catch (Exception e) {
            log.error("读取支付宝密钥文件失败: path={}", path);
            throw new RenException("读取支付宝密钥文件失败");
        }
    }

    /**
     * 剥离 PEM 头尾与所有空白，仅保留 base64 内容。
     *
     * 支付宝 SDK 的 getPrivateKeyFromPKCS8 / getPublicKeyFromX509 会直接对入参做
     * Base64 解码，并不识别 PEM 头（"-----BEGIN ...-----"），因此必须去掉头尾行与换行。
     */
    private static String stripPem(String pem) {
        if (StringUtils.isBlank(pem)) {
            return "";
        }
        return pem.replaceAll("-----BEGIN [^-]+-----", "")
                .replaceAll("-----END [^-]+-----", "")
                .replaceAll("\\s+", "");
    }

    /**
     * 转义 JSON 字符串中的反斜杠与双引号，防止 subject 破坏 bizContent。
     */
    private static String escapeJson(String s) {
        if (s == null) {
            return "";
        }
        return s.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private static String abbreviate(String s) {
        if (s == null) {
            return "未知错误";
        }
        return s.length() > 200 ? s.substring(0, 200) : s;
    }
}
