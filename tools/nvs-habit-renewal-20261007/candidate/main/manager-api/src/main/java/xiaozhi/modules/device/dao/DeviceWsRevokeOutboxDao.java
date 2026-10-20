package xiaozhi.modules.device.dao;

import org.apache.ibatis.annotations.Mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import xiaozhi.modules.device.entity.DeviceWsRevokeOutboxEntity;

@Mapper
public interface DeviceWsRevokeOutboxDao extends BaseMapper<DeviceWsRevokeOutboxEntity> {
}
