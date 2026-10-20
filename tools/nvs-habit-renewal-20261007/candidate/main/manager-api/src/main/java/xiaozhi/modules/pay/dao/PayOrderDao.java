package xiaozhi.modules.pay.dao;

import org.apache.ibatis.annotations.Mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import xiaozhi.modules.pay.entity.PayOrderEntity;

/**
 * 支付订单 DAO
 */
@Mapper
public interface PayOrderDao extends BaseMapper<PayOrderEntity> {
}
