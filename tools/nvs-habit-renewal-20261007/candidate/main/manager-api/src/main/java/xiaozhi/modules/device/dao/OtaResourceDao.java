package xiaozhi.modules.device.dao;

import org.apache.ibatis.annotations.Mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import xiaozhi.modules.device.entity.OtaResourceEntity;

/**
 * OTA 资源包管理（表情包、壁纸等）
 */
@Mapper
public interface OtaResourceDao extends BaseMapper<OtaResourceEntity> {

}

