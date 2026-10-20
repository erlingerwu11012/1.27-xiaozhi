package xiaozhi.modules.habit.dao;

import org.apache.ibatis.annotations.Mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import xiaozhi.modules.habit.entity.HabitEntity;

/**
 * 手动习惯管理 DAO
 */
@Mapper
public interface HabitDao extends BaseMapper<HabitEntity> {
}
