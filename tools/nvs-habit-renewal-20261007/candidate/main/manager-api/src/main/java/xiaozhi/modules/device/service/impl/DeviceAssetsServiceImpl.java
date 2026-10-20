package xiaozhi.modules.device.service.impl;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.exception.ErrorCode;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.redis.RedisUtils;
import xiaozhi.common.user.UserDetail;
import xiaozhi.modules.device.dao.AiDeviceAssetsDao;
import xiaozhi.modules.device.dto.DeviceAssetUploadDTO;
import xiaozhi.modules.device.entity.AiDeviceAssetsEntity;
import xiaozhi.modules.device.service.DeviceAssetsService;
import xiaozhi.modules.device.util.AssetsBinaryPacker;
import xiaozhi.modules.device.vo.DeviceAssetCheckUpdateVO;
import xiaozhi.modules.device.vo.DeviceAssetListItemVO;
import xiaozhi.modules.security.user.SecurityUser;
import xiaozhi.modules.sys.service.SysParamsService;

@Slf4j
@Service
@RequiredArgsConstructor
public class DeviceAssetsServiceImpl implements DeviceAssetsService {

    private static final String UPLOAD_BASE = "uploads";
    private static final String ALLOWED_EXT = "jpg,jpeg,png,gif,webp";

    private final AiDeviceAssetsDao aiDeviceAssetsDao;
    private final RestTemplate restTemplate;
    private final RedisUtils redisUtils;
    private final SysParamsService sysParamsService;

    @Value("${xiaozhi.upload.base-dir:uploads}")
    private String uploadBaseDir;

    @Value("${xiaozhi.upload.base-url:}")
    private String uploadBaseUrl;

    @Value("${xiaozhi.server.push-url:}")
    private String pushUrl;

    @Override
    public DeviceAssetUploadDTO uploadImage(String deviceId, String fileType, MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new RenException(ErrorCode.INTERNAL_SERVER_ERROR, "上传文件不能为空");
        }
        if (StringUtils.isBlank(deviceId)) {
            throw new RenException(ErrorCode.INTERNAL_SERVER_ERROR, "设备ID不能为空");
        }
        String type = StringUtils.isNotBlank(fileType) ? fileType.toLowerCase() : "wallpaper";
        if (!"emoji".equals(type) && !"wallpaper".equals(type)) {
            throw new RenException(ErrorCode.INTERNAL_SERVER_ERROR, "fileType 仅支持 emoji 或 wallpaper");
        }

        String originalFilename = file.getOriginalFilename();
        if (StringUtils.isBlank(originalFilename)) {
            throw new RenException(ErrorCode.INTERNAL_SERVER_ERROR, "文件名不能为空");
        }
        String ext = originalFilename.substring(originalFilename.lastIndexOf(".") + 1).toLowerCase();
        if (!ALLOWED_EXT.contains(ext)) {
            throw new RenException(ErrorCode.INTERNAL_SERVER_ERROR, "仅支持图片格式: " + ALLOWED_EXT);
        }

        Path basePath = Paths.get(uploadBaseDir, type);
        try {
            if (!Files.exists(basePath)) {
                Files.createDirectories(basePath);
            }
        } catch (IOException e) {
            log.error("创建上传目录失败: {}", basePath, e);
            throw new RenException(ErrorCode.INTERNAL_SERVER_ERROR, "创建上传目录失败");
        }

        String savedName = UUID.randomUUID().toString().replace("-", "") + "." + ext;
        Path filePath = basePath.resolve(savedName);
        try {
            Files.copy(file.getInputStream(), filePath);
        } catch (IOException e) {
            log.error("保存文件失败: {}", filePath, e);
            throw new RenException(ErrorCode.INTERNAL_SERVER_ERROR, "保存文件失败");
        }

        String fileUrl = UPLOAD_BASE + "/" + type + "/" + savedName;

        int nextVersion = nextVersionForDevice(deviceId, type);
        AiDeviceAssetsEntity entity = new AiDeviceAssetsEntity();
        entity.setDeviceId(deviceId);
        entity.setFileUrl(fileUrl);
        entity.setFileType(type);
        entity.setVersion(nextVersion);
        try {
            UserDetail user = SecurityUser.getUser();
            if (user != null) {
                entity.setCreator(user.getId());
            }
        } catch (Exception ignored) {
        }
        aiDeviceAssetsDao.insert(entity);

        DeviceAssetUploadDTO dto = new DeviceAssetUploadDTO();
        dto.setFileUrl(fileUrl);
        dto.setVersion(nextVersion);
        dto.setFileType(type);
        dto.setDeviceId(deviceId);
        return dto;
    }

    @Override
    public List<DeviceAssetListItemVO> listByDevice(String deviceId) {
        if (StringUtils.isBlank(deviceId)) {
            return new ArrayList<>();
        }
        LambdaQueryWrapper<AiDeviceAssetsEntity> q = new LambdaQueryWrapper<>();
        q.eq(AiDeviceAssetsEntity::getDeviceId, deviceId)
                .orderByDesc(AiDeviceAssetsEntity::getVersion);
        List<AiDeviceAssetsEntity> list = aiDeviceAssetsDao.selectList(q);
        List<DeviceAssetListItemVO> result = new ArrayList<>();
        for (AiDeviceAssetsEntity e : list) {
            DeviceAssetListItemVO vo = new DeviceAssetListItemVO();
            vo.setId(e.getId());
            vo.setFileUrl(e.getFileUrl());
            vo.setFileType(e.getFileType());
            vo.setVersion(e.getVersion());
            result.add(vo);
        }
        return result;
    }

    @Override
    public DeviceAssetCheckUpdateVO checkUpdate(String deviceId, Integer currentVersion) {
        if (StringUtils.isBlank(deviceId)) {
            DeviceAssetCheckUpdateVO vo = new DeviceAssetCheckUpdateVO();
            vo.setDeviceId(deviceId);
            vo.setHasUpdate(false);
            vo.setAssets(new ArrayList<>());
            return vo;
        }

        LambdaQueryWrapper<AiDeviceAssetsEntity> q = new LambdaQueryWrapper<>();
        q.eq(AiDeviceAssetsEntity::getDeviceId, deviceId)
                .orderByDesc(AiDeviceAssetsEntity::getVersion);
        List<AiDeviceAssetsEntity> list = aiDeviceAssetsDao.selectList(q);

        int maxVersion = list.stream()
                .mapToInt(AiDeviceAssetsEntity::getVersion)
                .max()
                .orElse(0);

        boolean hasUpdate = currentVersion != null && maxVersion > currentVersion;

        List<DeviceAssetCheckUpdateVO.AssetItemVO> assets = new ArrayList<>();
        java.util.Set<String> addedTypes = new java.util.HashSet<>();
        for (AiDeviceAssetsEntity e : list) {
            if (addedTypes.contains(e.getFileType())) {
                continue;
            }
            addedTypes.add(e.getFileType());
            DeviceAssetCheckUpdateVO.AssetItemVO item = new DeviceAssetCheckUpdateVO.AssetItemVO();
            item.setFileType(e.getFileType());
            item.setFileUrl(e.getFileUrl());
            item.setVersion(e.getVersion());
            assets.add(item);
        }

        DeviceAssetCheckUpdateVO vo = new DeviceAssetCheckUpdateVO();
        vo.setDeviceId(deviceId);
        vo.setHasUpdate(hasUpdate);
        vo.setAssets(assets);
        return vo;
    }

    @Override
    public String createSpiffsImage(String deviceId) {
        if (StringUtils.isBlank(deviceId)) {
            throw new RenException(ErrorCode.INTERNAL_SERVER_ERROR, "设备ID不能为空");
        }
        List<DeviceAssetListItemVO> assets = listByDevice(deviceId);
        if (assets == null || assets.isEmpty()) {
            throw new RenException(ErrorCode.INTERNAL_SERVER_ERROR, "该设备暂无资源可打包");
        }

        Path basePath = Paths.get(uploadBaseDir).toAbsolutePath();
        try {
            // 收集所有文件为 AssetFile 列表
            List<AssetsBinaryPacker.AssetFile> assetFiles = new ArrayList<>();
            for (DeviceAssetListItemVO vo : assets) {
                String fileUrl = vo.getFileUrl();
                if (StringUtils.isBlank(fileUrl)) continue;
                String[] parts = fileUrl.split("/");
                if (parts.length < 3) continue;
                String type = parts[1];
                String fileName = parts[parts.length - 1];
                Path src = basePath.resolve(type).resolve(fileName);
                if (!Files.exists(src)) {
                    log.warn("资源文件不存在，跳过: {}", src);
                    continue;
                }
                byte[] data = Files.readAllBytes(src);
                assetFiles.add(new AssetsBinaryPacker.AssetFile(fileName, data));
            }

            if (assetFiles.isEmpty()) {
                throw new RenException(ErrorCode.INTERNAL_SERVER_ERROR, "没有有效的资源文件可打包");
            }

            // 生成 index.json 并加入打包列表
            String indexJson = buildIndexJson(assets);
            assetFiles.add(new AssetsBinaryPacker.AssetFile("index.json",
                    indexJson.getBytes(java.nio.charset.StandardCharsets.UTF_8)));

            // 使用自定义二进制格式打包
            byte[] binData = AssetsBinaryPacker.pack(assetFiles);

            // 写入输出文件
            Path tempDir = basePath.resolve("temp");
            Files.createDirectories(tempDir);
            Path outFile = tempDir.resolve(deviceId + "_assets.bin");
            Files.write(outFile, binData);

            String relativePath = UPLOAD_BASE + "/temp/" + deviceId + "_assets.bin";
            if (StringUtils.isNotBlank(uploadBaseUrl)) {
                String base = uploadBaseUrl.endsWith("/") ? uploadBaseUrl.substring(0, uploadBaseUrl.length() - 1) : uploadBaseUrl;
                return base + "/" + relativePath;
            }
            return relativePath;
        } catch (IOException e) {
            log.error("资源打包 IO 异常", e);
            throw new RenException(ErrorCode.INTERNAL_SERVER_ERROR, "资源打包失败: " + e.getMessage());
        }
    }

    /**
     * 根据资源列表生成 index.json（简化版，包含表情映射和壁纸信息）
     */
    private String buildIndexJson(List<DeviceAssetListItemVO> assets) {
        StringBuilder sb = new StringBuilder();
        sb.append("{\"version\":1,\"files\":[");
        boolean first = true;
        for (DeviceAssetListItemVO vo : assets) {
            if (StringUtils.isBlank(vo.getFileUrl())) continue;
            String[] parts = vo.getFileUrl().split("/");
            String fileName = parts[parts.length - 1];
            if (!first) sb.append(",");
            sb.append("{\"name\":\"").append(fileName).append("\",\"type\":\"").append(vo.getFileType()).append("\"}");
            first = false;
        }
        sb.append("]}");
        return sb.toString();
    }

    @Override
    public String syncAssets(String deviceId) {
        if (StringUtils.isBlank(deviceId)) {
            throw new RenException(ErrorCode.INTERNAL_SERVER_ERROR, "设备ID不能为空");
        }
        String downloadUrl = createSpiffsImage(deviceId);
        // 存入 Redis，设备轮询 checkUpdate 时可获取（24小时过期）
        String pendingKey = "assets:pending:" + deviceId;
        redisUtils.set(pendingKey, downloadUrl);
        // 尝试通过 WebSocket 推送（设备可能不在线）
        pushUpdateAssetsToDevice(deviceId, downloadUrl);
        return downloadUrl;
    }

    /**
     * 通过 xiaozhi-server 的 HTTP 接口向设备 WebSocket 推送 update_assets 指令
     */
    private void pushUpdateAssetsToDevice(String deviceId, String url) {
        if (StringUtils.isBlank(pushUrl)) {
            log.info("未配置 xiaozhi.server.push-url，跳过向设备推送 update_assets");
            return;
        }
        try {
            Map<String, Object> payload = new HashMap<>();
            payload.put("type", "update_assets");
            payload.put("url", url);
            Map<String, Object> body = new HashMap<>();
            body.put("device_id", deviceId);
            body.put("payload", payload);
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            // 与 xiaozhi-server /api/v1/device/send 服务间鉴权对齐（server.secret）
            String secret = sysParamsService.getValue(Constant.SERVER_SECRET, true);
            if (StringUtils.isNotBlank(secret)) {
                headers.setBearerAuth(secret);
            }
            HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);
            restTemplate.postForObject(pushUrl, entity, String.class);
            log.info("已向设备 {} 推送 update_assets, url={}", deviceId, url);
        } catch (Exception e) {
            log.warn("向设备推送 update_assets 失败: deviceId={}, url={}", deviceId, url, e);
        }
    }

    private static String readFully(InputStream is) throws IOException {
        byte[] buf = new byte[4096];
        StringBuilder sb = new StringBuilder();
        int n;
        while ((n = is.read(buf)) > 0) {
            sb.append(new String(buf, 0, n, java.nio.charset.StandardCharsets.UTF_8));
        }
        return sb.toString();
    }

    private static void deleteRecursively(Path path) throws IOException {
        if (Files.isDirectory(path)) {
            try (var stream = Files.list(path)) {
                for (Path p : stream.toList()) {
                    deleteRecursively(p);
                }
            }
        }
        Files.delete(path);
    }

    private int nextVersionForDevice(String deviceId, String fileType) {
        LambdaQueryWrapper<AiDeviceAssetsEntity> q = new LambdaQueryWrapper<>();
        q.eq(AiDeviceAssetsEntity::getDeviceId, deviceId)
                .eq(AiDeviceAssetsEntity::getFileType, fileType)
                .orderByDesc(AiDeviceAssetsEntity::getVersion)
                .last("LIMIT 1");
        AiDeviceAssetsEntity one = aiDeviceAssetsDao.selectOne(q);
        return (one == null ? 0 : one.getVersion()) + 1;
    }
}
