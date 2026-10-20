package xiaozhi.modules.pay.service.impl;

import org.springframework.stereotype.Service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.pay.config.PayProperties;
import xiaozhi.modules.pay.constant.PayConstants;
import xiaozhi.modules.pay.dao.PayOrderDao;
import xiaozhi.modules.pay.entity.PayOrderEntity;
import xiaozhi.modules.pay.service.MockPayService;
import xiaozhi.modules.pay.service.PaymentDeliveryService;
import xiaozhi.modules.pay.vo.PayOrderVO;

/**
 * Mock 支付实现：仅用于测试/管理员场景。
 *
 * 生产默认关闭（mockEnabled=false），此时 channel=mock 下单与 mockNotify 均拒绝。
 * 支付成功后的发货（one-api topup -> delivered）统一走 PaymentDeliveryService。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class MockPayServiceImpl implements MockPayService {

    private final PayOrderDao payOrderDao;
    private final PaymentDeliveryService paymentDeliveryService;
    private final PayProperties payProperties;

    @Override
    public boolean isEnabled() {
        return payProperties.isMockEnabled();
    }

    @Override
    public PayOrderVO mockNotify(Long userId, String orderNo) {
        if (!isEnabled()) {
            throw new RenException(PayConstants.MSG_MOCK_DISABLED);
        }

        PayOrderEntity order = payOrderDao.selectOne(
                new QueryWrapper<PayOrderEntity>().eq("out_trade_no", orderNo));
        if (order == null) {
            throw new RenException("订单不存在");
        }
        if (!userId.equals(order.getUserId())) {
            throw new RenException("无权操作该订单");
        }

        // 统一发货（含 pending->paid、one-api topup、delivered，幂等）
        return paymentDeliveryService.deliver(orderNo, "MOCK_" + orderNo);
    }
}
