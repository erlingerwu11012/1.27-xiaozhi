package xiaozhi.modules.device.controller;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Map;
import java.util.UUID;

import org.apache.commons.lang3.StringUtils;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.Parameters;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.page.PageData;
import xiaozhi.common.redis.RedisKeys;
import xiaozhi.common.redis.RedisUtils;
import xiaozhi.common.utils.Result;
import xiaozhi.common.validator.ValidatorUtils;
import xiaozhi.modules.device.entity.OtaResourceEntity;
import xiaozhi.modules.device.service.DeviceAssetsService;
import xiaozhi.modules.device.service.OtaResourceService;

/**
 * OTA 资源包管理（表情包、壁纸等）
 *
 * 说明：
 * - 路径前缀：/otaResource
 * - 与固件 OTA 管理（/otaMag）区分开，避免混淆
 */
@Tag(name = "设备管理", description = "OTA 资源包相关接口（表情包、壁纸等）")
@RestController
@RequiredArgsConstructor
@RequestMapping("/otaResource")
public class OtaResourceController {

    private final OtaResourceService otaResourceService;
    private final DeviceAssetsService deviceAssetsService;
    private final RedisUtils redisUtils;

    @GetMapping
    @Operation(summary = "分页查询 OTA 资源包信息")
    @Parameters({
            @Parameter(name = Constant.PAGE, description = "当前页码，从1开始", required = true),
            @Parameter(name = Constant.LIMIT, description = "每页显示记录数", required = true)
    })
    public Result<PageData<OtaResourceEntity>> page(@Parameter(hidden = true) @RequestParam Map<String, Object> params) {
        ValidatorUtils.validateEntity(params);
        PageData<OtaResourceEntity> page = otaResourceService.page(params);
        return new Result<PageData<OtaResourceEntity>>().ok(page);
    }

    @GetMapping("{id}")
    @Operation(summary = "获取单个 OTA 资源包信息")
    public Result<OtaResourceEntity> get(@PathVariable("id") String id) {
        OtaResourceEntity data = otaResourceService.selectById(id);
        return new Result<OtaResourceEntity>().ok(data);
    }

    @PostMapping
    @Operation(summary = "保存 OTA 资源包信息")
    public Result<Void> save(@RequestBody OtaResourceEntity entity) {
        if (entity == null) {
            return new Result<Void>().error("资源信息不能为空");
        }
        if (StringUtils.isBlank(entity.getResourceName())) {
            return new Result<Void>().error("资源名称不能为空");
        }
        if (StringUtils.isBlank(entity.getResourceType())) {
            return new Result<Void>().error("资源类型不能为空");
        }
        if (StringUtils.isBlank(entity.getVersion())) {
            return new Result<Void>().error("版本号不能为空");
        }
        if (StringUtils.isBlank(entity.getResourcePath())) {
            return new Result<Void>().error("资源文件路径不能为空");
        }
        // emoji_pack 类型必须指定动作槽位
        if ("emoji_pack".equals(entity.getResourceType()) && StringUtils.isBlank(entity.getEmojiSlot())) {
            return new Result<Void>().error("表情包必须指定动作槽位（emojiSlot）");
        }
        otaResourceService.save(entity);
        return new Result<>();
    }

    @PutMapping("/{id}")
    @Operation(summary = "修改 OTA 资源包信息")
    public Result<?> update(@PathVariable("id") String id, @RequestBody OtaResourceEntity entity) {
        if (entity == null) {
            return new Result<>().error("资源信息不能为空");
        }
        entity.setId(id);
        otaResourceService.update(entity);
        return new Result<>();
    }

    @DeleteMapping("/{id}")
    @Operation(summary = "删除 OTA 资源包")
    public Result<Void> delete(@PathVariable("id") String[] ids) {
        if (ids == null || ids.length == 0) {
            return new Result<Void>().error("删除的资源ID不能为空");
        }
        otaResourceService.delete(ids);
        return new Result<>();
    }

    @PostMapping("/upload")
    @Operation(summary = "上传 OTA 资源包文件（表情包、壁纸等）")
    public Result<String> uploadResource(@RequestParam("file") MultipartFile file) {
        if (file.isEmpty()) {
            return new Result<String>().error("上传文件不能为空");
        }

        String originalFilename = file.getOriginalFilename();
        if (originalFilename == null) {
            return new Result<String>().error("文件名不能为空");
        }

        String extension = originalFilename.substring(originalFilename.lastIndexOf(".")).toLowerCase();
        // 支持图片格式（壁纸/表情）以及 zip 压缩包
        java.util.Set<String> allowedExt = new java.util.HashSet<>(java.util.Arrays.asList(
                ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".zip"
        ));
        if (!allowedExt.contains(extension)) {
            return new Result<String>().error("只允许上传图片（JPG/PNG/GIF/BMP/WebP）或 .zip 格式的文件");
        }

        // assets 分区大小 0x780000 = 7,864,320 字节（7.5MB）
        // 壁纸单文件限制 512KB，表情单文件限制 256KB，此处统一按 512KB 做服务端兜底校验
        long maxBytes = 512L * 1024;
        if (file.getSize() > maxBytes) {
            return new Result<String>().error("文件大小超出限制（最大 512KB）");
        }

        try {
            String md5 = calculateMD5(file);

            String uploadDir = "uploadfile/resource";
            Path uploadPath = Paths.get(uploadDir);
            if (!Files.exists(uploadPath)) {
                Files.createDirectories(uploadPath);
            }

            String uniqueFileName = md5 + extension;
            Path filePath = uploadPath.resolve(uniqueFileName);

            if (Files.exists(filePath)) {
                // 已存在相同 MD5 的文件，直接复用路径
                return new Result<String>().ok(filePath.toString());
            }

            Files.copy(file.getInputStream(), filePath);
            return new Result<String>().ok(filePath.toString());
        } catch (IOException | NoSuchAlgorithmException e) {
            return new Result<String>().error("文件上传失败：" + e.getMessage());
        }
    }

    private String calculateMD5(MultipartFile file) throws IOException, NoSuchAlgorithmException {
        MessageDigest md = MessageDigest.getInstance("MD5");
        byte[] digest = md.digest(file.getBytes());
        StringBuilder sb = new StringBuilder();
        for (byte b : digest) {
            sb.append(String.format("%02x", b));
        }
        return sb.toString();
    }

    @PostMapping("/burn/{deviceId}")
    @Operation(summary = "烧录资源到设备（打包 assets 二进制 + 推送下载指令）")
    public Result<String> burnToDevice(@PathVariable("deviceId") String deviceId) {
        if (StringUtils.isBlank(deviceId)) {
            return new Result<String>().error("设备ID不能为空");
        }
        try {
            String downloadUrl = deviceAssetsService.syncAssets(deviceId);
            return new Result<String>().ok(downloadUrl);
        } catch (Exception e) {
            return new Result<String>().error("烧录失败: " + e.getMessage());
        }
    }

    @GetMapping("/burn/status/{deviceId}")
    @Operation(summary = "查询设备烧录任务状态")
    public Result<Map<String, Object>> burnStatus(@PathVariable("deviceId") String deviceId) {
        // 从 Redis 查询该设备是否有待下载的 assets URL
        String key = "assets:pending:" + deviceId;
        Object url = redisUtils.get(key);
        Map<String, Object> status = new java.util.HashMap<>();
        if (url != null) {
            status.put("pending", true);
            status.put("url", url.toString());
        } else {
            status.put("pending", false);
        }
        return new Result<Map<String, Object>>().ok(status);
    }

    @GetMapping("/downloadBin/{uuid}")
    @Operation(summary = "设备下载 assets.bin 文件")
    public ResponseEntity<byte[]> downloadBin(@PathVariable("uuid") String uuid) {
        // 从 Redis 获取文件路径
        String key = RedisKeys.getOtaIdKey(uuid);
        String filePath = (String) redisUtils.get(key);
        if (StringUtils.isBlank(filePath)) {
            return ResponseEntity.notFound().build();
        }

        // 检查下载次数（限制 3 次）
        String countKey = RedisKeys.getOtaDownloadCountKey(uuid);
        Integer count = (Integer) redisUtils.get(countKey);
        if (count == null) count = 0;
        if (count >= 3) {
            redisUtils.delete(countKey);
            redisUtils.delete(key);
            return ResponseEntity.notFound().build();
        }
        redisUtils.set(countKey, count + 1);

        try {
            Path path = Paths.get(filePath);
            if (!Files.exists(path)) {
                return ResponseEntity.notFound().build();
            }
            byte[] data = Files.readAllBytes(path);
            return ResponseEntity.ok()
                    .contentType(MediaType.APPLICATION_OCTET_STREAM)
                    .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"assets.bin\"")
                    .body(data);
        } catch (IOException e) {
            return ResponseEntity.internalServerError().build();
        }
    }

    @GetMapping("/checkUpdate")
    @Operation(summary = "设备启动时轮询是否有待烧录的资源更新")
    public Result<Map<String, Object>> checkUpdate(@RequestParam("deviceId") String deviceId,
                                                    @RequestParam(value = "currentVersion", required = false) Integer currentVersion) {
        if (StringUtils.isBlank(deviceId)) {
            return new Result<Map<String, Object>>().error("设备ID不能为空");
        }
        // 检查 Redis 中是否有待下载的 assets URL
        String pendingKey = "assets:pending:" + deviceId;
        Object pendingUrl = redisUtils.get(pendingKey);
        Map<String, Object> result = new java.util.HashMap<>();
        if (pendingUrl != null) {
            result.put("hasUpdate", true);
            result.put("url", pendingUrl.toString());
            // 设备取走后删除待处理标记
            redisUtils.delete(pendingKey);
        } else {
            result.put("hasUpdate", false);
        }
        return new Result<Map<String, Object>>().ok(result);
    }
}

