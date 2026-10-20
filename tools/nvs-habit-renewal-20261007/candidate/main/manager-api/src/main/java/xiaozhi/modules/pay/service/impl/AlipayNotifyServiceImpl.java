package xiaozhi.modules.pay.service.impl;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Date;
import java.util.Map;
import java.util.TreeMap;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.pay.config.AlipayProperties;
import xiaozhi.modules.pay.constant.PayConstants;
import xiaozhi.modules.pay.dao.PayNotifyLogDao;
import xiaozhi.modules.pay.dao.PayOrderDao;
import xiaozhi.modules.pay.entity.PayNotifyLogEntity;
import xiaozhi.modules.pay.entity.PayOrderEntity;
import xiaozhi.modules.pay.service.AlipayNotifyService;
import xiaozhi.modules.pay.service.AlipayService;
import xiaozhi.modules.pay.service.PaymentDeliveryService;

/**
 * 支付宝异步通知处理。
 *
 * 处理流程（fail-closed）：
 * 1. 记录 notify_log（脱敏摘要）；
 * 2. 验签失败 -> 仅记录日志，不改订单，返回 failure；
 * 3. 校验 app_id / out_trade_no / total_amount / trade_status；
 * 4. 仅 TRADE_SUCCESS / TRADE_FINISHED 触发发货（deliver 内幂等）；
 * 5. 成功返回 success，失败返回 failure。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AlipayNotifyServiceImpl implements AlipayNotifyService {

    private static final String TRADE_SUCCESS = "TRADE_SUCCESS";
    private static final String TRADE_FINISHED = "TRADE_FINISHED";

    private final AlipayService alipayService;
    private final AlipayProperties alipayProperties;
    private final PaymentDeliveryService paymentDeliveryService;
    private final PayOrderDao payOrderDao;
    private final PayNotifyLogDao payNotifyLogDao;

    @Override
    public boolean handleNotify(Map<String, String> params) {
        String orderNo = params.get("out_trade_no");
        String tradeStatus = params.get("trade_status");

        // 1. 先落一条 notify_log（失败也记录，便于审计）
        PayNotifyLogEntity logEntity = new PayNotifyLogEntity();
        logEntity.setOrderNo(orderNo == null ? "" : orderNo);
        logEntity.setChannel(PayConstants.CHANNEL_ALIPAY);
        logEntity.setNotifyType(tradeStatus);
        logEntity.setRawBody(buildMaskedSummary(params));
        logEntity.setCreatedAt(new Date());

        // 2. 验签（失败仅记录，不改订单）
        if (!alipayService.verifyNotifySign(params)) {
            logEntity.setStatus("failed");
            logEntity.setErrorMsg("验签失败");
            payNotifyLogDao.insert(logEntity);
            log.warn("支付宝异步通知验签失败: outTradeNo={}", orderNo);
            return false;
        }

        // 3. 校验 app_id
        String appId = params.get("app_id");
        if (!alipayProperties.getAppId().equals(appId)) {
            logEntity.setStatus("failed");
            logEntity.setErrorMsg("app_id 不匹配");
            payNotifyLogDao.insert(logEntity);
            log.warn("支付宝异步通知 app_id 不匹配: expect={}, got={}", alipayProperties.getAppId(), appId);
            return false;
        }

        // 4. 校验 out_trade_no 存在
        if (StringUtils.isBlank(orderNo)) {
            logEntity.setStatus("failed");
            logEntity.setErrorMsg("out_trade_no 为空");
            payNotifyLogDao.insert(logEntity);
            return false;
        }

        // 5. 校验金额一致（以本地订单为准，防止篡改）
        PayOrderEntity order = payOrderDao.selectOne(
                new com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<PayOrderEntity>()
                        .eq("out_trade_no", orderNo));
        if (order == null) {
            logEntity.setStatus("failed");
            logEntity.setErrorMsg("订单不存在");
            payNotifyLogDao.insert(logEntity);
            log.warn("支付宝异步通知订单不存在: outTradeNo={}", orderNo);
            return false;
        }
        if (!amountMatches(params.get("total_amount"), order.getAmountCents())) {
            logEntity.setStatus("failed");
            logEntity.setErrorMsg("金额不一致");
            payNotifyLogDao.insert(logEntity);
            log.warn("支付宝异步通知金额不一致: outTradeNo={}, notifyAmount={}, orderCents={}",
                    orderNo, params.get("total_amount"), order.getAmountCents());
            return false;
        }

        // 6. 仅成功状态触发发货
        if (!TRADE_SUCCESS.equals(tradeStatus) && !TRADE_FINISHED.equals(tradeStatus)) {
            logEntity.setStatus("ignored");
            logEntity.setErrorMsg("trade_status=" + tradeStatus + " 不触发发货");
            payNotifyLogDao.insert(logEntity);
            log.info("支付宝异步通知非成功状态，忽略: outTradeNo={}, tradeStatus={}", orderNo, tradeStatus);
            return true;
        }

        // 7. 发货（幂等）
        try {
            paymentDeliveryService.deliver(orderNo, params.get("trade_no"));
            logEntity.setStatus("success");
            payNotifyLogDao.insert(logEntity);
            return true;
        } catch (RenException e) {
            logEntity.setStatus("failed");
            logEntity.setErrorMsg(abbreviate(e.getMsg()));
            payNotifyLogDao.insert(logEntity);
            log.error("支付宝异步通知发货失败: outTradeNo={}, err={}", orderNo, e.getMsg());
            return false;
        } catch (Exception e) {
            logEntity.setStatus("failed");
            logEntity.setErrorMsg("发货异常: " + abbreviate(e.getMessage()));
            payNotifyLogDao.insert(logEntity);
            log.error("支付宝异步通知发货异常: outTradeNo={}", orderNo, e);
            return false;
        }
    }

    /**
     * 金额校验：notify 的 total_amount（元，字符串）与订单 amount_cents（分）是否一致。
     */
    private boolean amountMatches(String totalAmount, Integer amountCents) {
        if (StringUtils.isBlank(totalAmount) || amountCents == null) {
            return false;
        }
        try {
            BigDecimal notifyYuan = new BigDecimal(totalAmount);
            BigDecimal orderYuan = BigDecimal.valueOf(amountCents)
                    .divide(BigDecimal.valueOf(100), 2, RoundingMode.HALF_UP);
            return notifyYuan.compareTo(orderYuan) == 0;
        } catch (NumberFormatException e) {
            return false;
        }
    }

    /**
     * 构造脱敏摘要：仅保留可审计的非敏感字段；buyer 类字段打码。
     */
    private String buildMaskedSummary(Map<String, String> params) {
        Map<String, String> sorted = new TreeMap<>(params);
        StringBuilder sb = new StringBuilder("{");
        boolean first = true;
        for (Map.Entry<String, String> e : sorted.entrySet()) {
            String key = e.getKey();
            String value = e.getValue();
            if (!first) {
                sb.append(", ");
            }
            first = false;
            if (isSensitive(key)) {
                sb.append("\"").append(key).append("\":\"").append(mask(value)).append("\"");
            } else if ("sign".equals(key)) {
                sb.append("\"").append(key).append("\":\"***\"");
            } else {
                sb.append("\"").append(key).append("\":\"").append(value).append("\"");
            }
        }
        sb.append("}");
        return sb.toString();
    }

    private boolean isSensitive(String key) {
        return key != null && (key.contains("buyer_id")
                || key.contains("buyer_logon_id")
                || key.contains("open_id")
                || key.contains("buyer_open_id"));
    }

    private static String mask(String s) {
        if (s == null) {
            return "***";
        }
        if (s.length() <= 4) {
            return "***";
        }
        return s.substring(0, 2) + "***" + s.substring(s.length() - 2);
    }

    private static String abbreviate(String s) {
        if (s == null) {
            return "处理失败";
        }
        return s.length() > 500 ? s.substring(0, 500) : s;
    }
}
