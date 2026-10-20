package xiaozhi.modules.pay.service;

import java.util.Map;

import xiaozhi.common.page.PageData;
import xiaozhi.common.service.BaseService;
import xiaozhi.modules.pay.dto.OrderCreateDTO;
import xiaozhi.modules.pay.entity.PayOrderEntity;
import xiaozhi.modules.pay.vo.PayOrderVO;

/**
 * 支付订单 Service
 */
public interface PayOrderService extends BaseService<PayOrderEntity> {

    /**
     * 创建订单（仅 mock 渠道当前可真正创建）
     */
    PayOrderVO create(Long userId, OrderCreateDTO dto);

    /**
     * 查询当前用户自己的订单
     */
    PayOrderVO queryByOrderNo(Long userId, String orderNo);

    /**
     * 分页查询当前用户订单
     */
    PageData<PayOrderVO> page(Long userId, Map<String, Object> params);
}
