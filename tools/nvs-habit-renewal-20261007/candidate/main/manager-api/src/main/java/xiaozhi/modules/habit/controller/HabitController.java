package xiaozhi.modules.habit.controller;

import java.util.List;

import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.habit.dto.HabitDTO;
import xiaozhi.modules.habit.entity.HabitEntity;
import xiaozhi.modules.habit.service.HabitService;
import xiaozhi.modules.security.user.SecurityUser;

/**
 * 手动习惯管理接口（每个用户只能管理自己的习惯）
 */
@Tag(name = "手动习惯管理", description = "用户手动创建习惯提醒相关接口")
@Slf4j
@RestController
@RequiredArgsConstructor
@RequestMapping("/habits")
public class HabitController {

    private final HabitService habitService;
    private final xiaozhi.modules.habit.service.HabitSyncService sync;
    @GetMapping("/options")
    public Result<java.util.Map<String,Object>> options() {return new Result<java.util.Map<String,Object>>().ok(sync.options(SecurityUser.getUserId()));}
    @org.springframework.web.bind.annotation.PutMapping("/{id}")
    public Result<Void> update(@PathVariable Integer id, @Valid @RequestBody HabitDTO dto) {sync.update(SecurityUser.getUserId(),id,dto);return new Result<>();}

    @GetMapping
    @Operation(summary = "查询当前用户的手动习惯列表")
    public Result<List<HabitEntity>> list(
            @RequestParam(value = "enabledOnly", defaultValue = "true") boolean enabledOnly) {
        Long userId = SecurityUser.getUser().getId();
        List<HabitEntity> list = habitService.listManual(userId, enabledOnly);
        return new Result<List<HabitEntity>>().ok(list);
    }

    @PostMapping
    @Operation(summary = "创建手动习惯")
    public Result<HabitEntity> create(@Valid @RequestBody HabitDTO dto) {
        Long userId = SecurityUser.getUser().getId();
        HabitEntity entity = habitService.create(userId, dto);
        return new Result<HabitEntity>().ok(entity);
    }

    @DeleteMapping("/{id}")
    @Operation(summary = "删除手动习惯（软删除，只能删除自己的习惯）")
    public Result<Void> delete(@PathVariable("id") Integer id) {
        Long userId = SecurityUser.getUser().getId();
        habitService.softDelete(userId, id);
        return new Result<>();
    }
}
