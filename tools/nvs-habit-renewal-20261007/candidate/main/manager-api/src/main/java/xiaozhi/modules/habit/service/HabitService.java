package xiaozhi.modules.habit.service;

import java.util.List;

import xiaozhi.common.service.BaseService;
import xiaozhi.modules.habit.dto.HabitDTO;
import xiaozhi.modules.habit.entity.HabitEntity;

/**
 * 手动习惯管理 Service
 */
public interface HabitService extends BaseService<HabitEntity> {

    /**
     * 查询手动习惯列表（仅 source=manual，且属于指定用户）
     *
     * @param userId      当前登录用户ID
     * @param enabledOnly 是否只返回启用的习惯
     */
    List<HabitEntity> listManual(Long userId, boolean enabledOnly);

    /**
     * 创建手动习惯
     */
    HabitEntity create(Long userId, HabitDTO dto);

    /**
     * 软删除习惯（enabled=0，synced=0），只能删除属于该用户的习惯
     *
     * @param userId 当前登录用户ID
     * @param id     习惯ID
     */
    void softDelete(Long userId, Integer id);
}
