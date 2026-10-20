package xiaozhi.modules.rolepack.service.impl;

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
import xiaozhi.modules.rolepack.config.RolePackProperties;
import xiaozhi.modules.rolepack.dao.RolePackDao;
import xiaozhi.modules.rolepack.dto.RolePackPublishDTO;
import xiaozhi.modules.rolepack.dto.RolePackUpdateDTO;
import xiaozhi.modules.rolepack.entity.RolePackEntity;
import xiaozhi.modules.rolepack.service.RolePackAuditService;
import xiaozhi.modules.rolepack.service.RolePackService;
import xiaozhi.modules.rolepack.util.DownloadBaseUrlValidator;
import xiaozhi.modules.rolepack.util.HttpRangeResponder;
import xiaozhi.modules.rolepack.util.PreviewMediaValidator;
import xiaozhi.modules.rolepack.util.RolePackConstants;
import xiaozhi.modules.rolepack.util.RolePackPreviewAccess;
import xiaozhi.modules.rolepack.util.RolePackPublishIdentity;
import xiaozhi.modules.rolepack.util.RolePackSigner;
import xiaozhi.modules.rolepack.util.SpineBundleValidator;
import xiaozhi.modules.rolepack.util.VersionCompareUtil;
import xiaozhi.modules.rolepack.vo.RolePackCatalogItemVO;
import xiaozhi.modules.rolepack.vo.RolePackInspectVO;

@Slf4j
@Service
@RequiredArgsConstructor
public class RolePackServiceImpl implements RolePackService {

    private final RolePackDao rolePackDao;
    private final RolePackProperties properties;
    private final RolePackSigner signer;
    private final RolePackAuditService auditService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Override
    public RolePackInspectVO inspect(MultipartFile spineBin) {
        byte[] bytes = readSpineBytes(spineBin);
        try {
            RolePackPublishIdentity.Resolved resolved = RolePackPublishIdentity.resolve(bytes, null, null);
            return toInspectVo(resolved.getInfo());
        } catch (IllegalArgumentException | IOException e) {
            throw new RenException("角色包校验失败: " + e.getMessage());
        }
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public RolePackEntity publish(Long adminUserId, RolePackPublishDTO meta, MultipartFile spineBin,
            MultipartFile previewImage, MultipartFile previewVideo) {
        signer.requireReady();
        if (meta == null || StringUtils.isBlank(meta.getDisplayName())) {
            throw new RenException("显示名称不能为空");
        }
        byte[] bytes = readSpineBytes(spineBin);
        RolePackPublishIdentity.Resolved resolved;
        try {
            resolved = RolePackPublishIdentity.resolve(bytes, meta.getPackId(), meta.getVersion());
        } catch (IllegalArgumentException | IOException e) {
            throw new RenException("角色包校验失败: " + e.getMessage());
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
        String objectKey = packId + "/" + version + "/spine.bin";
        Path dest = resolveStoragePath(objectKey);
        try {
            Files.createDirectories(dest.getParent());
            Files.write(dest, bytes);
        } catch (IOException e) {
            throw new RenException("写入角色包存储失败");
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
        String signature = signer.signPack(packId, packId, version,
                bytes.length, sha256, minFw, contentUrl);

        RolePackEntity existing = getByPackId(packId);
        Date now = new Date();
        String status = Boolean.FALSE.equals(meta.getPublishNow())
                ? RolePackConstants.STATUS_DRAFT
                : RolePackConstants.STATUS_PUBLISHED;

        if (existing == null) {
            RolePackEntity entity = new RolePackEntity();
            entity.setPackId(packId);
            entity.setDisplayName(meta.getDisplayName().trim());
            entity.setDescription(meta.getDescription());
            entity.setVersion(version);
            entity.setObjectKey(objectKey);
            entity.setSize((long) bytes.length);
            entity.setSha256(sha256);
            entity.setSignature(signature);
            entity.setSignatureAlgorithm(RolePackConstants.SIG_ALG_ES256);
            entity.setMinFw(minFw);
            entity.setBoardModelAllowlist(allowlistJson);
            entity.setPreviewImageObjectKey(imageKey);
            entity.setPreviewVideoObjectKey(videoKey);
            entity.setStatus(status);
            entity.setCreatedBy(adminUserId);
            entity.setCreatedAt(now);
            entity.setUpdatedAt(now);
            rolePackDao.insert(entity);
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
        existing.setSignatureAlgorithm(RolePackConstants.SIG_ALG_ES256);
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
        rolePackDao.updateById(existing);
        auditService.log("PUBLISH_UPDATE", adminUserId, null, packId, null,
                "version=" + version + ",size=" + bytes.length, null);
        return existing;
    }

    @Override
    public ResponseEntity<byte[]> servePublishedPreview(String packId, String kind, String rangeHeader) {
        RolePackEntity pack = getByPackId(packId);
        if (!RolePackPreviewAccess.canServe(pack, kind)) {
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
    public RolePackEntity updateMeta(Long adminUserId, String packId, RolePackUpdateDTO dto) {
        RolePackEntity entity = requireExists(packId);
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
            if (!List.of(RolePackConstants.STATUS_DRAFT, RolePackConstants.STATUS_PUBLISHED,
                    RolePackConstants.STATUS_DISABLED).contains(dto.getStatus())) {
                throw new RenException("非法 status");
            }
            entity.setStatus(dto.getStatus());
        }
        entity.setUpdatedAt(new Date());
        rolePackDao.updateById(entity);
        auditService.log("UPDATE_META", adminUserId, null, packId, null, dto.getStatus(), null);
        return entity;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public RolePackEntity disable(Long adminUserId, String packId) {
        RolePackEntity entity = requireExists(packId);
        entity.setStatus(RolePackConstants.STATUS_DISABLED);
        entity.setUpdatedAt(new Date());
        rolePackDao.updateById(entity);
        auditService.log("DISABLE", adminUserId, null, packId, null, null, null);
        return entity;
    }

    @Override
    public List<RolePackCatalogItemVO> catalogPublished() {
        List<RolePackEntity> list = rolePackDao.selectList(new LambdaQueryWrapper<RolePackEntity>()
                .eq(RolePackEntity::getStatus, RolePackConstants.STATUS_PUBLISHED)
                .orderByDesc(RolePackEntity::getUpdatedAt));
        return list.stream().map(this::toCatalogVo).collect(Collectors.toList());
    }

    @Override
    public RolePackCatalogItemVO getPublished(String packId) {
        RolePackEntity entity = requirePublished(packId);
        return toCatalogVo(entity);
    }

    @Override
    public RolePackCatalogItemVO toCatalogItem(RolePackEntity entity) {
        return toCatalogVo(entity);
    }

    @Override
    public RolePackEntity requirePublished(String packId) {
        RolePackEntity entity = requireExists(packId);
        if (!RolePackConstants.STATUS_PUBLISHED.equals(entity.getStatus())) {
            throw new RenException("角色包未发布或已禁用");
        }
        return entity;
    }

    @Override
    public RolePackEntity getByPackId(String packId) {
        return rolePackDao.selectOne(new LambdaQueryWrapper<RolePackEntity>()
                .eq(RolePackEntity::getPackId, packId)
                .last("LIMIT 1"));
    }

    @Override
    public byte[] readPackBytes(RolePackEntity pack) {
        Path path = resolveStoragePath(pack.getObjectKey());
        try {
            if (!Files.exists(path)) {
                throw new RenException("角色包文件不存在");
            }
            byte[] data = Files.readAllBytes(path);
            if (data.length != pack.getSize()) {
                throw new RenException("角色包文件大小与元数据不一致");
            }
            String actual = sha256Hex(data);
            if (!actual.equalsIgnoreCase(pack.getSha256())) {
                throw new RenException("角色包文件 SHA-256 与元数据不一致");
            }
            return data;
        } catch (IOException e) {
            throw new RenException("读取角色包失败");
        }
    }

    private RolePackEntity requireExists(String packId) {
        RolePackEntity entity = getByPackId(packId);
        if (entity == null) {
            throw new RenException("角色包不存在");
        }
        return entity;
    }

    private void validateMeta(RolePackPublishDTO meta) {
        // 兼容字段不再由客户端决定；保留方法避免误用
        if (meta == null || StringUtils.isBlank(meta.getDisplayName())) {
            throw new RenException("显示名称不能为空");
        }
    }

    public static void applyPreviewUrls(RolePackCatalogItemVO vo, String packId, String imageKey, String videoKey,
            String legacyPreviewUrl) {
        if (StringUtils.isNotBlank(imageKey)) {
            vo.setPreviewImageUrl("/role-packs/" + packId + "/preview-image");
        } else if (StringUtils.isNotBlank(legacyPreviewUrl)) {
            vo.setPreviewImageUrl(legacyPreviewUrl);
        }
        if (StringUtils.isNotBlank(videoKey)) {
            vo.setPreviewVideoUrl("/role-packs/" + packId + "/preview-video");
        }
        vo.setPreviewUrl(legacyPreviewUrl);
    }

    private RolePackInspectVO toInspectVo(SpineBundleValidator.BundleInfo info) {
        RolePackInspectVO vo = new RolePackInspectVO();
        vo.setPackId(info.getRoleId());
        vo.setVersion(info.getVersion());
        vo.setFormat(info.getFormat());
        vo.setSpineRuntimeVersion(info.getSpineRuntimeVersion());
        vo.setSkel(info.getSkel());
        vo.setAtlas(info.getAtlas());
        vo.setPng(info.getPng());
        vo.setSize((long) info.getPackSize());
        vo.setDefaultMinFw(requireDefaultMinFw());
        vo.setDefaultSupportedBoards(requireDefaultBoards());
        return vo;
    }

    private byte[] readSpineBytes(MultipartFile spineBin) {
        if (spineBin == null || spineBin.isEmpty()) {
            throw new RenException("请上传官方 mmap 格式 spine.bin（generated_spine.bin），不支持 ZIP");
        }
        byte[] bytes;
        try {
            bytes = spineBin.getBytes();
        } catch (IOException e) {
            throw new RenException("读取上传文件失败");
        }
        if (bytes.length <= 0 || bytes.length > RolePackConstants.MAX_PACK_SIZE) {
            throw new RenException("角色包大小必须 > 0 且 <= " + RolePackConstants.MAX_PACK_SIZE + " bytes");
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
        return base + "/role-packs/content/" + packId + "/" + version + "/spine.bin";
    }

    private RolePackCatalogItemVO toCatalogVo(RolePackEntity e) {
        RolePackCatalogItemVO vo = new RolePackCatalogItemVO();
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
