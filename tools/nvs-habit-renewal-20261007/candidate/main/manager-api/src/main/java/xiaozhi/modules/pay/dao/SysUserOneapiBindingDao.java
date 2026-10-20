package xiaozhi.modules.pay.dao;

import org.apache.ibatis.annotations.Mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import xiaozhi.modules.pay.entity.SysUserOneapiBindingEntity;

/**
 * 主系统用户与 one-api 用户绑定 DAO
 */
@Mapper
public interface SysUserOneapiBindingDao extends BaseMapper<SysUserOneapiBindingEntity> {
}
