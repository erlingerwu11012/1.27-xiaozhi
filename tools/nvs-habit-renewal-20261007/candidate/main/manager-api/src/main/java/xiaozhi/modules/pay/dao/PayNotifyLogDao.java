package xiaozhi.modules.pay.dao;

import org.apache.ibatis.annotations.Mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import xiaozhi.modules.pay.entity.PayNotifyLogEntity;

/**
 * 支付回调日志 DAO
 */
@Mapper
public interface PayNotifyLogDao extends BaseMapper<PayNotifyLogEntity> {
}
