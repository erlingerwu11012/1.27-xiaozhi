package xiaozhi.modules.wallpaperpack.service.impl;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.stream.Collectors;

import org.apache.commons.lang3.StringUtils;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.wallpaperpack.config.WallpaperPackProperties;
import xiaozhi.modules.wallpaperpack.dao.WallpaperPackDao;
import xiaozhi.modules.wallpaperpack.dto.WallpaperPackPublishDTO;
import xiaozhi.modules.wallpaperpack.dto.WallpaperPackUpdateDTO;
import xiaozhi.modules.wallpaperpack.entity.WallpaperPackEntity;
import xiaozhi.modules.wallpaperpack.service.WallpaperPackAuditService;
import xiaozhi.modules.wallpaperpack.service.WallpaperPackService;
import xiaozhi.modules.rolepack.util.DownloadBaseUrlValidator;
import xiaozhi.modules.rolepack.util.HttpRangeResponder;
import xiaozhi.modules.rolepack.util.PreviewMediaValidator;
import xiaozhi.modules.wallpaperpack.util.WallpaperPackConstants;
import xiaozhi.modules.wallpaperpack.util.WallpaperPackPreviewAccess;
import xiaozhi.modules.wallpaperpack.util.WallpaperPackPublishIdentity;
import xiaozhi.modules.rolepack.util.RolePackSigner;
import xiaozhi.modules.wallpaperpack.util.WallpaperBundleValidator;
import xiaozhi.modules.rolepack.util.VersionCompareUtil;
import xiaozhi.modules.wallpaperpack.vo.WallpaperPackCatalogItemVO;
import xiaozhi.modules.wallpaperpack.vo.WallpaperPackInspectVO;

@Slf4j
@Service
@RequiredArgsConstructor
public class WallpaperPackServiceImpl implements WallpaperPackService {

    private final WallpaperPackDao wallpaperPackDao;
    private final WallpaperPackProperties properties;
    private final RolePackSigner signer;
    private final WallpaperPackAuditService auditService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Override
    public WallpaperPackInspectVO inspect(MultipartFile wallpaperBin) {
        byte[] bytes = readWallpaperBytes(wallpaperBin);
        try {
            WallpaperPackPublishIdentity.Resolved resolved = WallpaperPackPublishIdentity.resolve(bytes, null, null);
            return toInspectVo(resolved.getInfo());
        } catch (IllegalArgumentException | IOException e) {
            throw new RenException("壁纸包校验失败: " + e.getMessage());
        }
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public WallpaperPackEntity publish(Long adminUserId, WallpaperPackPublishDTO meta, MultipartFile wallpaperBin,
            MultipartFile previewImage, MultipartFile previewVideo) {
        signer.requireReady();
        if (meta == null || StringUtils.isBlank(meta.getDisplayName())) {
            throw new RenException("显示名称不能为空");
        }
        byte[] bytes = readWallpaperBytes(wallpaperBin);
        WallpaperPackPublishIdentity.Resolved resolved;
        try {
            resolved = WallpaperPackPublishIdentity.resolve(bytes, meta.getPackId(), meta.getVersion());
        } catch (IllegalArgumentException | IOException e) {
            throw new RenException("壁纸包校验失败: " + e.getMessage());
        }
        String packId = resolved.getPackId();
        String version = resolved.getVersion();
        if (!packId.matches("^[A-Za-z0-9_-]+$")) {
            throw new RenException("pack_id 仅允许 [A-Za-z0-9_-]");
        }
        if (!VersionCompareUtil.isValidSemVerLike(version)) {
            throw new RenException("version 格式非法");
        }

        String minFw = requireDefaultMinFw();
        List<String> boards = requireDefaultBoards();

        String sha256 = sha256Hex(bytes);
        String objectKey = packId + "/" + version + "/wallpaper.bin";
        Path dest = resolveStoragePath(objectKey);
        try {
            Files.createDirectories(dest.getParent());
            Files.write(dest, bytes);
        } catch (IOException e) {
            throw new RenException("写入壁纸包存储失败");
        }

        String imageKey = null;
        String videoKey = null;
        if (previewImage != null && !previewImage.isEmpty()) {
            imageKey = storePreview(packId, version, "image", previewImage);
        }
        if (previewVideo != null && !previewVideo.isEmpty()) {
            videoKey = storePreview(packId, version, "video", previewVideo);
        }

        String allowlistJson;
        try {
            allowlistJson = objectMapper.writeValueAsString(boards);
        } catch (Exception e) {
            throw new RenException("board_model_allowlist 序列化失败");
        }

        String contentUrl = buildStableContentUrl(packId, version);
        String signature = signer.signWallpaperPack(packId, version,
                bytes.length, sha256, minFw, contentUrl);

        WallpaperPackEntity existing = getByPackId(packId);
        Date now = new Date();
        String status = Boolean.FALSE.equals(meta.getPublishNow())
                ? WallpaperPackConstants.STATUS_DRAFT
                : WallpaperPackConstants.STATUS_PUBLISHED;

        if (existing == null) {
            WallpaperPackEntity entity = new WallpaperPackEntity();
            entity.setPackId(packId);
            entity.setDisplayName(meta.getDisplayName().trim());
            entity.setDescription(meta.getDescription());
            entity.setVersion(version);
            entity.setObjectKey(objectKey);
            entity.setSize((long) bytes.length);
            entity.setSha256(sha256);
            entity.setSignature(signature);
            entity.setSignatureAlgorithm(WallpaperPackConstants.SIG_ALG_ES256);
            entity.setMinFw(minFw);
            entity.setBoardModelAllowlist(allowlistJson);
            entity.setPreviewImageObjectKey(imageKey);
            entity.setPreviewVideoObjectKey(videoKey);
            entity.setStatus(status);
            entity.setCreatedBy(adminUserId);
            entity.setCreatedAt(now);
            entity.setUpdatedAt(now);
            wallpaperPackDao.insert(entity);
            auditService.log("PUBLISH", adminUserId, null, packId, null,
                    "version=" + version + ",size=" + bytes.length, null);
            return entity;
        }

        existing.setDisplayName(meta.getDisplayName().trim());
        existing.setDescription(meta.getDescription());
        existing.setVersion(version);
        existing.setObjectKey(objectKey);
        existing.setSize((long) bytes.length);
        existing.setSha256(sha256);
        existing.setSignature(signature);
        existing.setSignatureAlgorithm(WallpaperPackConstants.SIG_ALG_ES256);
        existing.setMinFw(minFw);
        existing.setBoardModelAllowlist(allowlistJson);
        if (imageKey != null) {
            existing.setPreviewImageObjectKey(imageKey);
        }
        if (videoKey != null) {
            existing.setPreviewVideoObjectKey(videoKey);
        }
        existing.setStatus(status);
        existing.setUpdatedAt(now);
        wallpaperPackDao.updateById(existing);
        auditService.log("PUBLISH_UPDATE", adminUserId, null, packId, null,
                "version=" + version + ",size=" + bytes.length, null);
        return existing;
    }

    @Override
    public ResponseEntity<byte[]> servePublishedPreview(String packId, String kind, String rangeHeader) {
        WallpaperPackEntity pack = getByPackId(packId);
        if (!WallpaperPackPreviewAccess.canServe(pack, kind)) {
            throw new RenException("预览媒体不可用");
        }
        String objectKey = "image".equals(kind) ? pack.getPreviewImageObjectKey() : pack.getPreviewVideoObjectKey();
        if (StringUtils.isBlank(objectKey)) {
            throw new RenException("预览媒体不可用");
        }
        Path path = resolveStoragePath(objectKey);
        byte[] data;
        try {
            if (!Files.exists(path) || !Files.isRegularFile(path)) {
                throw new RenException("预览媒体不可用");
            }
            data = Files.readAllBytes(path);
        } catch (IOException e) {
            throw new RenException("预览媒体不可用");
        }
        String contentType = contentTypeOf(objectKey, kind);
        return HttpRangeResponder.respond(data, contentType, rangeHeader);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public WallpaperPackEntity updateMeta(Long adminUserId, String packId, WallpaperPackUpdateDTO dto) {
        WallpaperPackEntity entity = requireExists(packId);
        if (StringUtils.isNotBlank(dto.getDisplayName())) {
            entity.setDisplayName(dto.getDisplayName().trim());
        }
        if (dto.getDescription() != null) {
            entity.setDescription(dto.getDescription());
        }
        if (dto.getPreviewUrl() != null) {
            entity.setPreviewUrl(dto.getPreviewUrl());
        }
        if (StringUtils.isNotBlank(dto.getMinFw())) {
            if (!VersionCompareUtil.isValidSemVerLike(dto.getMinFw())) {
                throw new RenException("min_fw 格式非法");
            }
            entity.setMinFw(dto.getMinFw());
        }
        if (dto.getBoardModelAllowlist() != null) {
            if (dto.getBoardModelAllowlist().isEmpty()) {
                throw new RenException("board_model_allowlist 不能为空");
            }
            try {
                entity.setBoardModelAllowlist(objectMapper.writeValueAsString(dto.getBoardModelAllowlist()));
            } catch (Exception e) {
                throw new RenException("board_model_allowlist 序列化失败");
            }
        }
        if (StringUtils.isNotBlank(dto.getStatus())) {
            if (!List.of(WallpaperPackConstants.STATUS_DRAFT, WallpaperPackConstants.STATUS_PUBLISHED,
                    WallpaperPackConstants.STATUS_DISABLED).contains(dto.getStatus())) {
                throw new RenException("非法 status");
            }
            entity.setStatus(dto.getStatus());
        }
        entity.setUpdatedAt(new Date());
        wallpaperPackDao.updateById(entity);
        auditService.log("UPDATE_META", adminUserId, null, packId, null, dto.getStatus(), null);
        return entity;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public WallpaperPackEntity disable(Long adminUserId, String packId) {
        WallpaperPackEntity entity = requireExists(packId);
        entity.setStatus(WallpaperPackConstants.STATUS_DISABLED);
        entity.setUpdatedAt(new Date());
        wallpaperPackDao.updateById(entity);
        auditService.log("DISABLE", adminUserId, null, packId, null, null, null);
        return entity;
    }

    @Override
    public List<WallpaperPackCatalogItemVO> catalogPublished() {
        List<WallpaperPackEntity> list = wallpaperPackDao.selectList(new LambdaQueryWrapper<WallpaperPackEntity>()
                .eq(WallpaperPackEntity::getStatus, WallpaperPackConstants.STATUS_PUBLISHED)
                .orderByDesc(WallpaperPackEntity::getUpdatedAt));
        return list.stream().map(this::toCatalogVo).collect(Collectors.toList());
    }

    @Override
    public WallpaperPackCatalogItemVO getPublished(String packId) {
        WallpaperPackEntity entity = requirePublished(packId);
        return toCatalogVo(entity);
    }

    @Override
    public WallpaperPackCatalogItemVO toCatalogItem(WallpaperPackEntity entity) {
        return toCatalogVo(entity);
    }

    @Override
    public WallpaperPackEntity requirePublished(String packId) {
        WallpaperPackEntity entity = requireExists(packId);
        if (!WallpaperPackConstants.STATUS_PUBLISHED.equals(entity.getStatus())) {
            throw new RenException("壁纸包未发布或已禁用");
        }
        return entity;
    }

    @Override
    public WallpaperPackEntity getByPackId(String packId) {
        return wallpaperPackDao.selectOne(new LambdaQueryWrapper<WallpaperPackEntity>()
                .eq(WallpaperPackEntity::getPackId, packId)
                .last("LIMIT 1"));
    }

    @Override
    public byte[] readPackBytes(WallpaperPackEntity pack) {
        Path path = resolveStoragePath(pack.getObjectKey());
        try {
            if (!Files.exists(path)) {
                throw new RenException("壁纸包文件不存在");
            }
            byte[] data = Files.readAllBytes(path);
            if (data.length != pack.getSize()) {
                throw new RenException("壁纸包文件大小与元数据不一致");
            }
            String actual = sha256Hex(data);
            if (!actual.equalsIgnoreCase(pack.getSha256())) {
                throw new RenException("壁纸包文件 SHA-256 与元数据不一致");
            }
            return data;
        } catch (IOException e) {
            throw new RenException("读取壁纸包失败");
        }
    }

    private WallpaperPackEntity requireExists(String packId) {
        WallpaperPackEntity entity = getByPackId(packId);
        if (entity == null) {
            throw new RenException("壁纸包不存在");
        }
        return entity;
    }

    private void validateMeta(WallpaperPackPublishDTO meta) {
        // 兼容字段不再由客户端决定；保留方法避免误用
        if (meta == null || StringUtils.isBlank(meta.getDisplayName())) {
            throw new RenException("显示名称不能为空");
        }
    }

    public static void applyPreviewUrls(WallpaperPackCatalogItemVO vo, String packId, String imageKey, String videoKey,
            String legacyPreviewUrl) {
        if (StringUtils.isNotBlank(imageKey)) {
            vo.setPreviewImageUrl("/wallpaper-packs/" + packId + "/preview-image");
        } else if (StringUtils.isNotBlank(legacyPreviewUrl)) {
            vo.setPreviewImageUrl(legacyPreviewUrl);
        }
        if (StringUtils.isNotBlank(videoKey)) {
            vo.setPreviewVideoUrl("/wallpaper-packs/" + packId + "/preview-video");
        }
        vo.setPreviewUrl(legacyPreviewUrl);
    }

    private WallpaperPackInspectVO toInspectVo(WallpaperBundleValidator.BundleInfo info) {
        WallpaperPackInspectVO vo = new WallpaperPackInspectVO();
        vo.setPackId(info.getPackId());
        vo.setVersion(info.getVersion());
        vo.setFormat(info.getFormat());
        vo.setDefaultId(info.getDefaultId());
        vo.setItemCount(info.getItemCount());
        vo.setSize((long) info.getPackSize());
        vo.setDefaultMinFw(requireDefaultMinFw());
        vo.setDefaultSupportedBoards(requireDefaultBoards());
        return vo;
    }

    private byte[] readWallpaperBytes(MultipartFile wallpaperBin) {
        if (wallpaperBin == null || wallpaperBin.isEmpty()) {
            throw new RenException("请上传官方 mmap 格式 wallpaper.bin（generated_wallpaper.bin），不支持 ZIP");
        }
        byte[] bytes;
        try {
            bytes = wallpaperBin.getBytes();
        } catch (IOException e) {
            throw new RenException("读取上传文件失败");
        }
        if (bytes.length <= 0 || bytes.length > WallpaperPackConstants.MAX_PACK_SIZE) {
            throw new RenException("壁纸包大小必须 > 0 且 <= " + WallpaperPackConstants.MAX_PACK_SIZE + " bytes");
        }
        return bytes;
    }

    private String storePreview(String packId, String version, String kind, MultipartFile file) {
        byte[] data;
        try {
            data = file.getBytes();
        } catch (IOException e) {
            throw new RenException("读取预览媒体失败");
        }
        PreviewMediaValidator.Result result;
        try {
            if ("image".equals(kind)) {
                result = PreviewMediaValidator.requireImage(data, file.getOriginalFilename(), file.getContentType());
            } else {
                result = PreviewMediaValidator.requireVideo(data, file.getOriginalFilename(), file.getContentType());
            }
        } catch (IllegalArgumentException e) {
            throw new RenException(e.getMessage());
        }
        String objectKey = PreviewMediaValidator.previewObjectKey(packId, version, kind, result.storeExt());
        Path dest = resolveStoragePath(objectKey);
        try {
            Files.createDirectories(dest.getParent());
            Files.write(dest, data);
        } catch (IOException e) {
            throw new RenException("写入预览媒体失败");
        }
        return objectKey;
    }

    private String contentTypeOf(String objectKey, String kind) {
        String lower = objectKey.toLowerCase();
        if (lower.endsWith(".png")) {
            return "image/png";
        }
        if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) {
            return "image/jpeg";
        }
        if (lower.endsWith(".webp")) {
            return "image/webp";
        }
        if (lower.endsWith(".mp4")) {
            return "video/mp4";
        }
        if (lower.endsWith(".webm")) {
            return "video/webm";
        }
        return "image".equals(kind) ? "application/octet-stream" : "video/mp4";
    }

    private String requireDefaultMinFw() {
        String minFw = properties.getDefaultMinFw();
        if (!VersionCompareUtil.isValidSemVerLike(minFw)) {
            throw new RenException("xiaozhi.role-pack.default-min-fw 未配置或格式非法");
        }
        return minFw;
    }

    private List<String> requireDefaultBoards() {
        List<String> boards = properties.getDefaultSupportedBoards();
        if (boards == null || boards.isEmpty()) {
            throw new RenException("xiaozhi.role-pack.default-supported-boards 未配置");
        }
        List<String> out = new ArrayList<>();
        for (String board : boards) {
            if (StringUtils.isBlank(board)) {
                throw new RenException("xiaozhi.role-pack.default-supported-boards 含空项");
            }
            out.add(board.trim());
        }
        return out;
    }

    private Path resolveStoragePath(String objectKey) {
        if (objectKey.contains("..") || objectKey.startsWith("/") || objectKey.startsWith("\\")) {
            throw new RenException("非法 object_key");
        }
        Path base = Path.of(properties.getStorageDir()).toAbsolutePath().normalize();
        Path dest = base.resolve(objectKey).normalize();
        if (!dest.startsWith(base)) {
            throw new RenException("路径穿越被拒绝");
        }
        return dest;
    }

    /**
     * 包级审计用的稳定 https URL（无 token）。必须满足签名 URL 规则。
     */
    private String buildStableContentUrl(String packId, String version) {
        String base = DownloadBaseUrlValidator.requireValid(properties.getDownloadBaseUrl());
        return base + "/wallpaper-packs/content/" + packId + "/" + version + "/wallpaper.bin";
    }

    private WallpaperPackCatalogItemVO toCatalogVo(WallpaperPackEntity e) {
        WallpaperPackCatalogItemVO vo = new WallpaperPackCatalogItemVO();
        vo.setPackId(e.getPackId());
        vo.setDisplayName(e.getDisplayName());
        vo.setDescription(e.getDescription());
        vo.setVersion(e.getVersion());
        vo.setSize(e.getSize());
        vo.setMinFw(e.getMinFw());
        vo.setPreviewUrl(e.getPreviewUrl());
        applyPreviewUrls(vo, e.getPackId(), e.getPreviewImageObjectKey(), e.getPreviewVideoObjectKey(),
                e.getPreviewUrl());
        vo.setStatus(e.getStatus());
        vo.setBoardModelAllowlist(parseAllowlist(e.getBoardModelAllowlist()));
        return vo;
    }

    @SuppressWarnings("unchecked")
    private List<String> parseAllowlist(String json) {
        try {
            if (StringUtils.isBlank(json)) {
                return new ArrayList<>();
            }
            return objectMapper.readValue(json, List.class);
        } catch (Exception e) {
            return new ArrayList<>();
        }
    }

    public static String sha256Hex(byte[] data) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] dig = md.digest(data);
            StringBuilder sb = new StringBuilder();
            for (byte b : dig) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new RenException("计算 SHA-256 失败");
        }
    }
}
