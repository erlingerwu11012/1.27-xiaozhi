package xiaozhi.modules.useridentity.dao;

import org.apache.ibatis.annotations.Mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import xiaozhi.modules.useridentity.entity.UserIdentityEntity;

@Mapper
public interface UserIdentityDao extends BaseMapper<UserIdentityEntity> {
}
