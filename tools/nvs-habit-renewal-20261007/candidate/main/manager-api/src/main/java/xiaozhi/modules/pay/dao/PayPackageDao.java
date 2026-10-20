package xiaozhi.modules.pay.dao;

import org.apache.ibatis.annotations.Mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import xiaozhi.modules.pay.entity.PayPackageEntity;

/**
 * 支付套餐 DAO
 */
@Mapper
public interface PayPackageDao extends BaseMapper<PayPackageEntity> {
}
