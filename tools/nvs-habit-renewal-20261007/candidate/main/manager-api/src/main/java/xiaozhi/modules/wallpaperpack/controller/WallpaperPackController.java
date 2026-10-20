package xiaozhi.modules.wallpaperpack.controller;

import java.util.List;
import java.util.Map;

import org.apache.commons.lang3.StringUtils;
import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import com.fasterxml.jackson.databind.ObjectMapper;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.wallpaperpack.dto.WallpaperPackPublishDTO;
import xiaozhi.modules.wallpaperpack.dto.WallpaperPackUpdateDTO;
import xiaozhi.modules.wallpaperpack.entity.WallpaperPackEntity;
import xiaozhi.modules.wallpaperpack.service.WallpaperDeployService;
import xiaozhi.modules.wallpaperpack.service.WallpaperPackService;
import xiaozhi.modules.wallpaperpack.vo.WallpaperDeployTaskVO;
import xiaozhi.modules.wallpaperpack.vo.WallpaperPackCatalogItemVO;
import xiaozhi.modules.wallpaperpack.vo.WallpaperPackInspectVO;
import xiaozhi.modules.security.user.SecurityUser;

/**
 * 官方壁纸包 API。
 */
@Tag(name = "壁纸包")
@RestController
@RequestMapping("/wallpaper-packs")
@RequiredArgsConstructor
public class WallpaperPackController {

    private final WallpaperPackService wallpaperPackService;
    private final WallpaperDeployService wallpaperDeployService;
    private final ObjectMapper objectMapper;

    @GetMapping("/catalog")
    @Operation(summary = "官方已发布视觉角色目录")
    @RequiresPermissions("sys:role:normal")
    public Result<List<WallpaperPackCatalogItemVO>> catalog() {
        return new Result<List<WallpaperPackCatalogItemVO>>().ok(wallpaperPackService.catalogPublished());
    }

    @GetMapping("/{packId}/preview-image")
    @Operation(summary = "已发布角色封面图")
    public ResponseEntity<byte[]> previewImage(@PathVariable("packId") String packId,
            @RequestHeader(value = "Range", required = false) String range) {
        return servePreview(packId, "image", range);
    }

    @GetMapping("/{packId}/preview-video")
    @Operation(summary = "已发布角色演示视频")
    public ResponseEntity<byte[]> previewVideo(@PathVariable("packId") String packId,
            @RequestHeader(value = "Range", required = false) String range) {
        return servePreview(packId, "video", range);
    }

    @GetMapping("/{packId}")
    @Operation(summary = "查询已发布角色包详情")
    @RequiresPermissions("sys:role:normal")
    public Result<WallpaperPackCatalogItemVO> detail(@PathVariable("packId") String packId) {
        return new Result<WallpaperPackCatalogItemVO>().ok(wallpaperPackService.getPublished(packId));
    }

    @PostMapping("/{packId}/deploy/{deviceId}")
    @Operation(summary = "将官方角色下载到用户自己的设备")
    @RequiresPermissions("sys:role:normal")
    public Result<WallpaperDeployTaskVO> deploy(@PathVariable("packId") String packId,
            @PathVariable("deviceId") String deviceId) {
        Long userId = SecurityUser.getUser().getId();
        return new Result<WallpaperDeployTaskVO>().ok(wallpaperDeployService.deploy(userId, packId, deviceId));
    }

    @GetMapping("/tasks/{taskId}")
    @Operation(summary = "查询部署任务状态")
    @RequiresPermissions("sys:role:normal")
    public Result<WallpaperDeployTaskVO> task(@PathVariable("taskId") String taskId) {
        Long userId = SecurityUser.getUser().getId();
        return new Result<WallpaperDeployTaskVO>().ok(wallpaperDeployService.getTaskForUser(userId, taskId));
    }

    @PostMapping("/devices/{deviceId}/cancel-pending-spine")
    @Operation(summary = "取消指定设备 pending/queued/retrying 的 update_wallpaper 任务（保留历史，标记 cancelled）")
    @RequiresPermissions("sys:role:normal")
    public Result<Map<String, Object>> cancelPendingSpine(@PathVariable("deviceId") String deviceId,
            @RequestParam(value = "reason", required = false) String reason) {
        Long userId = SecurityUser.getUser().getId();
        var cancelled = wallpaperDeployService.cancelPendingUpdateWallpaper(
                deviceId, StringUtils.defaultIfBlank(reason, "user_cancel"), userId);
        Map<String, Object> body = new java.util.HashMap<>();
        body.put("deviceId", deviceId);
        body.put("cancelledCount", cancelled.size());
        body.put("tasks", cancelled);
        return new Result<Map<String, Object>>().ok(body);
    }

    @PostMapping(value = "/inspect", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @Operation(summary = "管理员解析 wallpaper.bin 内 metadata（不落库）")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<WallpaperPackInspectVO> inspect(
            @RequestParam(value = "spineBin", required = false) MultipartFile spineBin,
            @RequestParam(value = "file", required = false) MultipartFile file) {
        MultipartFile spine = firstNonEmpty(spineBin, file);
        return new Result<WallpaperPackInspectVO>().ok(wallpaperPackService.inspect(spine));
    }

    @PostMapping(value = "/publish", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    @Operation(summary = "管理员发布官方角色包")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<WallpaperPackCatalogItemVO> publish(
            @RequestParam(value = "displayName", required = false) String displayName,
            @RequestParam(value = "description", required = false) String description,
            @RequestParam(value = "spineBin", required = false) MultipartFile spineBin,
            @RequestParam(value = "file", required = false) MultipartFile file,
            @RequestParam(value = "previewImage", required = false) MultipartFile previewImage,
            @RequestParam(value = "previewVideo", required = false) MultipartFile previewVideo,
            @RequestParam(value = "meta", required = false) String metaJson,
            @RequestParam(value = "packId", required = false) String packId,
            @RequestParam(value = "version", required = false) String version)
            throws Exception {
        WallpaperPackPublishDTO meta = new WallpaperPackPublishDTO();
        if (StringUtils.isNotBlank(metaJson)) {
            meta = objectMapper.readValue(metaJson, WallpaperPackPublishDTO.class);
        }
        if (StringUtils.isNotBlank(displayName)) {
            meta.setDisplayName(displayName);
        }
        if (StringUtils.isNotBlank(description)) {
            meta.setDescription(description);
        }
        if (StringUtils.isNotBlank(packId)) {
            meta.setPackId(packId);
        }
        if (StringUtils.isNotBlank(version)) {
            meta.setVersion(version);
        }
        Long userId = SecurityUser.getUser().getId();
        WallpaperPackEntity entity = wallpaperPackService.publish(userId, meta, firstNonEmpty(spineBin, file),
                previewImage, previewVideo);
        return new Result<WallpaperPackCatalogItemVO>().ok(wallpaperPackService.toCatalogItem(entity));
    }

    @PutMapping("/{packId}")
    @Operation(summary = "管理员更新角色包元数据")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<WallpaperPackCatalogItemVO> update(@PathVariable("packId") String packId,
            @Valid @RequestBody WallpaperPackUpdateDTO dto) {
        Long userId = SecurityUser.getUser().getId();
        WallpaperPackEntity e = wallpaperPackService.updateMeta(userId, packId, dto);
        return new Result<WallpaperPackCatalogItemVO>().ok(wallpaperPackService.toCatalogItem(e));
    }

    @PostMapping("/{packId}/disable")
    @Operation(summary = "管理员禁用角色包")
    @RequiresPermissions("sys:role:superAdmin")
    public Result<Void> disable(@PathVariable("packId") String packId) {
        Long userId = SecurityUser.getUser().getId();
        wallpaperPackService.disable(userId, packId);
        return new Result<>();
    }

    private ResponseEntity<byte[]> servePreview(String packId, String kind, String range) {
        try {
            return wallpaperPackService.servePublishedPreview(packId, kind, range);
        } catch (RenException e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                    .header("X-Content-Type-Options", "nosniff")
                    .build();
        }
    }

    private static MultipartFile firstNonEmpty(MultipartFile a, MultipartFile b) {
        if (a != null && !a.isEmpty()) {
            return a;
        }
        return b;
    }
}
