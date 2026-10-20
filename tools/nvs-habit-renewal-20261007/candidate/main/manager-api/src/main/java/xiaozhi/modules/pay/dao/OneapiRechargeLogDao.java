package xiaozhi.modules.pay.dao;

import org.apache.ibatis.annotations.Mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import xiaozhi.modules.pay.entity.OneapiRechargeLogEntity;

/**
 * one-api 充值流水 DAO
 */
@Mapper
public interface OneapiRechargeLogDao extends BaseMapper<OneapiRechargeLogEntity> {
}
