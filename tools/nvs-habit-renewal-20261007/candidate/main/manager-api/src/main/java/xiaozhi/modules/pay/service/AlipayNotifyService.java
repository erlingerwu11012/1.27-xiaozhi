package xiaozhi.modules.pay.service;

import java.util.Map;

/**
 * 支付宝异步通知处理服务。
 */
public interface AlipayNotifyService {

    /**
     * 处理支付宝异步通知（application/x-www-form-urlencoded）。
     *
     * @param params 支付宝 POST 的 form 参数
     * @return true=应回写 "success"，false=应回写 "failure"
     */
    boolean handleNotify(Map<String, String> params);
}
