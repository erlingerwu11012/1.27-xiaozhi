package xiaozhi.modules.useridentity.service.impl;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.text.Normalizer;
import java.util.Locale;
import org.springframework.dao.DuplicateKeyException;
import xiaozhi.modules.useridentity.service.AccountIdentityStateService;
import xiaozhi.modules.face.service.FaceProxyService;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;

import lombok.RequiredArgsConstructor;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.agent.dao.AgentVoicePrintDao;
import xiaozhi.modules.agent.entity.AgentVoicePrintEntity;
import xiaozhi.modules.useridentity.dao.UserFaceBindingDao;
import xiaozhi.modules.useridentity.dao.UserIdentityDao;
import xiaozhi.modules.useridentity.entity.UserFaceBindingEntity;
import xiaozhi.modules.useridentity.entity.UserIdentityEntity;
import xiaozhi.modules.useridentity.service.UserIdentityService;
import xiaozhi.modules.useridentity.vo.UserIdentityVO;

@Service
@RequiredArgsConstructor
public class UserIdentityServiceImpl implements UserIdentityService {
    private static final String ACTIVE = "active";

    private final UserIdentityDao userIdentityDao;
    private final UserFaceBindingDao userFaceBindingDao;
    private final AgentVoicePrintDao agentVoicePrintDao;
    private final AccountIdentityStateService identityState;
    private final FaceProxyService faceProxy;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public UserIdentityVO create(Long accountId, String userId, String displayName) {
        identityState.lock(accountId);
        String normalizedUserId = AccountIdentityStateService.newId();
        String name = requireNickname(accountId, displayName, null);
        UserIdentityEntity entity = new UserIdentityEntity();
        entity.setAccountId(accountId);
        entity.setUserId(normalizedUserId);
        entity.setDisplayName(name);
        entity.setStatus(ACTIVE);
        entity.setKind("member");
        try { userIdentityDao.insert(entity); }
        catch (DuplicateKeyException e) { throw new RenException("昵称已重复"); }
        identityState.changed(accountId);
        return toVO(entity, List.of(), List.of());
    }

    @Override
    public List<UserIdentityVO> list(Long accountId) {
        List<UserIdentityEntity> users = userIdentityDao.selectList(new LambdaQueryWrapper<UserIdentityEntity>()
                .eq(UserIdentityEntity::getAccountId, accountId)
                .eq(UserIdentityEntity::getKind, "member")
                .orderByAsc(UserIdentityEntity::getCreateDate));
        List<UserIdentityVO> result = new ArrayList<>();
        for (UserIdentityEntity user : users) {
            result.add(toVO(user, faceIds(accountId, user.getUserId()), voiceIds(accountId, user.getUserId())));
        }
        return result;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public UserIdentityVO updateDisplayName(Long accountId, String userId, String displayName) {
        identityState.lock(accountId);
        UserIdentityEntity entity = requireActive(accountId, userId);
        entity.setDisplayName(requireNickname(accountId, displayName, userId));
        try { userIdentityDao.updateById(entity); }
        catch (DuplicateKeyException e) { throw new RenException("昵称已重复"); }
        identityState.changed(accountId);
        return toVO(entity, faceIds(accountId, entity.getUserId()), voiceIds(accountId, entity.getUserId()));
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void bindFace(Long accountId, String userId, String faceProfileId) {
        identityState.lock(accountId);
        requireActive(accountId, userId);
        String profileId = requireText(faceProfileId, "人脸 profile_id");
        // Account-scoped face JWT: never accept a foreign profile merely by its ID.
        faceProxy.getProfile(profileId);
        UserFaceBindingEntity existing = userFaceBindingDao.selectOne(new LambdaQueryWrapper<UserFaceBindingEntity>()
                .eq(UserFaceBindingEntity::getAccountId, accountId)
                .eq(UserFaceBindingEntity::getFaceProfileId, profileId));
        if (existing != null) {
            if (!requireText(userId, "user_id").equals(existing.getUserId())) {
                throw new RenException("该人脸档案已绑定到其他用户，请先解绑");
            }
            return;
        }
        UserFaceBindingEntity binding = new UserFaceBindingEntity();
        binding.setAccountId(accountId);
        binding.setUserId(requireText(userId, "user_id"));
        binding.setFaceProfileId(profileId);
        userFaceBindingDao.insert(binding);
        identityState.changed(accountId);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void unbindFace(Long accountId, String userId, String faceProfileId) {
        identityState.lock(accountId);
        userFaceBindingDao.delete(new LambdaQueryWrapper<UserFaceBindingEntity>()
                .eq(UserFaceBindingEntity::getAccountId, accountId)
                .eq(UserFaceBindingEntity::getUserId, requireText(userId, "user_id"))
                .eq(UserFaceBindingEntity::getFaceProfileId, requireText(faceProfileId, "人脸 profile_id")));
        identityState.changed(accountId);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void bindVoiceprint(Long accountId, String userId, String voiceprintId) {
        identityState.lock(accountId);
        identityState.requireCleanupCapability(accountId);
        requireActive(accountId, userId);
        AgentVoicePrintEntity voice = requireVoice(accountId, voiceprintId);
        if (!"ready".equals(voice.getBindingState()) || StringUtils.isBlank(voice.getVectorId())) {
            throw new RenException("声纹尚未注册成功");
        }
        String targetUserId = requireText(userId, "user_id");
        if (StringUtils.isNotBlank(voice.getUserId()) && !targetUserId.equals(voice.getUserId())) {
            throw new RenException("该声纹已绑定到其他用户，请先解绑");
        }
        voice.setUserId(targetUserId);
        agentVoicePrintDao.updateById(voice);
        identityState.changed(accountId);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void unbindVoiceprint(Long accountId, String userId, String voiceprintId) {
        identityState.lock(accountId);
        AgentVoicePrintEntity voice = requireVoice(accountId, voiceprintId);
        if (requireText(userId, "user_id").equals(voice.getUserId())) {
            agentVoicePrintDao.update(null,new com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper<AgentVoicePrintEntity>()
                .eq(AgentVoicePrintEntity::getId,voice.getId()).eq(AgentVoicePrintEntity::getCreator,accountId)
                .set(AgentVoicePrintEntity::getUserId,null));
            identityState.changed(accountId);
        }
    }

    @Override
    public List<String> unboundVoiceprintIds(Long accountId, String agentId) {
        LambdaQueryWrapper<AgentVoicePrintEntity> query = new LambdaQueryWrapper<AgentVoicePrintEntity>()
                .eq(AgentVoicePrintEntity::getCreator, accountId)
                .isNull(AgentVoicePrintEntity::getUserId);
        if (StringUtils.isNotBlank(agentId)) {
            query.eq(AgentVoicePrintEntity::getAgentId, agentId);
        }
        return agentVoicePrintDao.selectList(query).stream().map(AgentVoicePrintEntity::getId).toList();
    }

    @Override
    public List<String> boundFaceProfileIds(Long accountId) {
        return userFaceBindingDao.selectList(new LambdaQueryWrapper<UserFaceBindingEntity>()
                .eq(UserFaceBindingEntity::getAccountId, accountId))
                .stream().map(UserFaceBindingEntity::getFaceProfileId).toList();
    }

    @Override
    public Map<String, Object> getActiveUser(Long accountId, String userId) {
        UserIdentityEntity entity = findEntity(accountId, userId);
        if (entity == null || !ACTIVE.equals(entity.getStatus())) {
            return null;
        }
        return Map.of("user_id", entity.getUserId(), "display_name", entity.getDisplayName());
    }

    @Override
    public List<Map<String, Object>> getFaceBindings(Long accountId) {
        List<Map<String, Object>> result = new ArrayList<>();
        for (UserFaceBindingEntity binding : userFaceBindingDao.selectList(new LambdaQueryWrapper<UserFaceBindingEntity>()
                .eq(UserFaceBindingEntity::getAccountId, accountId))) {
            Map<String, Object> user = getActiveUser(accountId, binding.getUserId());
            if (user != null) {
                Map<String, Object> item = new HashMap<>(user);
                item.put("face_profile_id", binding.getFaceProfileId());
                result.add(item);
            }
        }
        return result;
    }

    @Override
    public List<Map<String, Object>> getDeviceDirectory(Long accountId) {
        List<Map<String, Object>> result = new ArrayList<>();
        for (UserIdentityEntity entity : userIdentityDao.selectList(new LambdaQueryWrapper<UserIdentityEntity>()
                .eq(UserIdentityEntity::getAccountId, accountId)
                .eq(UserIdentityEntity::getStatus, ACTIVE))) {
            result.add(Map.of("user_id", entity.getUserId(),
                    "display_name", entity.getDisplayName(),
                    "status", entity.getStatus()));
        }
        return result;
    }

    private UserIdentityEntity requireActive(Long accountId, String userId) {
        UserIdentityEntity entity = findEntity(accountId, userId);
        if (entity == null || !ACTIVE.equals(entity.getStatus()) || !"member".equals(entity.getKind())) {
            throw new RenException("用户不存在或已停用");
        }
        return entity;
    }

    private UserIdentityEntity findEntity(Long accountId, String userId) {
        return userIdentityDao.selectOne(new LambdaQueryWrapper<UserIdentityEntity>()
                .eq(UserIdentityEntity::getAccountId, accountId)
                .eq(UserIdentityEntity::getUserId, requireText(userId, "user_id")));
    }

    private AgentVoicePrintEntity requireVoice(Long accountId, String voiceprintId) {
        AgentVoicePrintEntity voice = agentVoicePrintDao.selectOne(new LambdaQueryWrapper<AgentVoicePrintEntity>()
                .eq(AgentVoicePrintEntity::getId, requireText(voiceprintId, "声纹ID"))
                .eq(AgentVoicePrintEntity::getCreator, accountId));
        if (voice == null) {
            throw new RenException("声纹不存在或不属于当前账号");
        }
        return voice;
    }

    private List<String> faceIds(Long accountId, String userId) {
        return userFaceBindingDao.selectList(new LambdaQueryWrapper<UserFaceBindingEntity>()
                .eq(UserFaceBindingEntity::getAccountId, accountId)
                .eq(UserFaceBindingEntity::getUserId, userId))
                .stream().map(UserFaceBindingEntity::getFaceProfileId).toList();
    }

    private List<String> voiceIds(Long accountId, String userId) {
        return agentVoicePrintDao.selectList(new LambdaQueryWrapper<AgentVoicePrintEntity>()
                .eq(AgentVoicePrintEntity::getCreator, accountId)
                .eq(AgentVoicePrintEntity::getUserId, userId))
                .stream().map(AgentVoicePrintEntity::getId).toList();
    }

    private UserIdentityVO toVO(UserIdentityEntity entity, List<String> faces, List<String> voices) {
        UserIdentityVO vo = new UserIdentityVO();
        vo.setUserId(entity.getUserId());
        vo.setDisplayName(entity.getDisplayName());
        vo.setStatus(entity.getStatus());
        vo.setFaceProfileIds(faces);
        vo.setVoiceprintIds(voices);
        return vo;
    }

    private String requireText(String value, String field) {
        String normalized = value == null ? "" : value.trim();
        if (normalized.isEmpty()) {
            throw new RenException(field + "不能为空");
        }
        return normalized;
    }

    private String requireNickname(Long accountId,String value,String except) {
        String name=Normalizer.normalize(requireText(value,"昵称"),Normalizer.Form.NFKC).trim();
        if (name.length()>64) throw new RenException("昵称不能超过64个字符");
        String key=name.toLowerCase(Locale.ROOT);
        for (UserIdentityEntity user:userIdentityDao.selectList(new LambdaQueryWrapper<UserIdentityEntity>()
                .eq(UserIdentityEntity::getAccountId,accountId).eq(UserIdentityEntity::getKind,"member"))) {
            if (!user.getUserId().equals(except) && Normalizer.normalize(user.getDisplayName(),Normalizer.Form.NFKC).trim().toLowerCase(Locale.ROOT).equals(key))
                throw new RenException("昵称已重复");
        }
        return name;
    }
}
