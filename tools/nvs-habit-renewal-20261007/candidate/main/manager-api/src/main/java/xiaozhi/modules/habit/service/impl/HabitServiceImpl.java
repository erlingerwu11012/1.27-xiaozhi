package xiaozhi.modules.habit.service.impl;

import java.util.List;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.service.impl.BaseServiceImpl;
import xiaozhi.modules.habit.dao.HabitDao;
import xiaozhi.modules.habit.dto.HabitDTO;
import xiaozhi.modules.habit.entity.HabitEntity;
import xiaozhi.modules.habit.service.HabitService;

@Slf4j
@Service
@RequiredArgsConstructor
public class HabitServiceImpl extends BaseServiceImpl<HabitDao, HabitEntity>
        implements HabitService {

    private final xiaozhi.modules.habit.service.HabitSyncService sync;

    @Override
    public List<HabitEntity> listManual(Long userId, boolean enabledOnly) {
        QueryWrapper<HabitEntity> wrapper = new QueryWrapper<>();
        wrapper.eq("source", "manual");
        wrapper.eq("user_id", userId);
        if (enabledOnly) {
            wrapper.eq("enabled", 1);
        }
        wrapper.orderByAsc("id");
        return baseDao.selectList(wrapper);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public HabitEntity create(Long userId, HabitDTO dto) {
        String name = sync.validateBinding(userId,dto);
        sync.validateContent(dto);
        HabitEntity entity = new HabitEntity();
        entity.setDescription(dto.getDescription().trim());
        entity.setHour(dto.getHour());
        entity.setMinute(dto.getMinute() != null ? dto.getMinute() : 0);
        entity.setAdvanceMinutes(dto.getAdvanceMinutes() != null ? dto.getAdvanceMinutes() : 2);
        entity.setSource("manual");
        entity.setEnabled(1);
        entity.setSynced(0);
        entity.setUserId(userId);
        entity.setRecipientPersonId(dto.getRecipientPersonId());
        entity.setRecipientDisplayName(name);
        entity.setSyncState("pending");
        entity.setConfigVersion(1L);

        // 生成 intent（若未提供）
        String intent = dto.getIntent();
        if (StringUtils.isBlank(intent)) {
            intent = dto.getDescription().trim()
                    .toLowerCase()
                    .replaceAll("[^\\w\\u4e00-\\u9fa5]", "_")
                    .replaceAll("_+", "_");
            if (intent.length() > 32) {
                intent = intent.substring(0, 32);
            }
        }
        while(intent.getBytes(java.nio.charset.StandardCharsets.UTF_8).length>64) intent=intent.substring(0,intent.length()-1);
        entity.setIntent(intent);

        if (StringUtils.isNotBlank(dto.getDeviceId())) {
            entity.setDeviceId(dto.getDeviceId().trim());
        }

        baseDao.insert(entity);
        return entity;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void softDelete(Long userId, Integer id) {
        HabitEntity entity = baseDao.selectById(id);
        if (entity == null) {
            throw new RenException("习惯不存在，id=" + id);
        }
        if (!"manual".equals(entity.getSource())) {
            throw new RenException("只能删除手动创建的习惯");
        }
        if (!userId.equals(entity.getUserId())) {
            throw new RenException("无权删除他人的习惯");
        }
        UpdateWrapper<HabitEntity> wrapper = new UpdateWrapper<>();
        wrapper.eq("id", id)
               .set("enabled", 0)
               .set("synced", 0)
               .set("sync_state", "pending")
               .set("sync_error", null)
               .setSql("config_version=config_version+1");
        baseDao.update(null, wrapper);
    }
}
