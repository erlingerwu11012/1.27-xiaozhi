package xiaozhi.modules.pay.service.impl;

import org.springframework.stereotype.Service;

import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.pay.service.WechatPayService;

/**
 * 微信支付占位实现：阶段1未接入真实微信支付 API v3。
 */
@Slf4j
@Service
public class WechatPayServiceImpl implements WechatPayService {

    @Override
    public boolean isConfigured() {
        return false;
    }

    @Override
    public Object createNativeOrder(Long orderId) {
        throw new RenException("微信支付未配置");
    }
}
