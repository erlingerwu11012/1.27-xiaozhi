package xiaozhi.modules.pay.service.impl;

import java.security.SecureRandom;

import org.apache.commons.lang3.StringUtils;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;

import cn.hutool.core.util.IdUtil;
import cn.hutool.core.util.RandomUtil;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.ErrorCode;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.pay.config.OneApiProperties;
import xiaozhi.modules.pay.constant.PayConstants;
import xiaozhi.modules.pay.dao.OneApiProvisioningDao;
import xiaozhi.modules.pay.dao.SysUserOneapiBindingDao;
import xiaozhi.modules.pay.dto.OneApiTokenRow;
import xiaozhi.modules.pay.dto.OneApiUserRow;
import xiaozhi.modules.pay.entity.SysUserOneapiBindingEntity;
import xiaozhi.modules.pay.service.OneApiProvisioningService;
import xiaozhi.modules.pay.util.OneApiTokenCipher;
import xiaozhi.modules.security.password.PasswordUtils;
import xiaozhi.modules.sys.dao.SysUserDao;
import xiaozhi.modules.sys.entity.SysUserEntity;

/**
 * one-api 计费账户开通实现。
 *
 * 策略：one-api 无管理员为用户创建 token 的官方 API，因此直接插入 one_api.users / one_api.tokens
 * 记录（仅创建，不改 quota）；token key 用 AES-256-GCM 加密后写入 sys_user_oneapi_binding。
 * 全程不打印 token / 密码 / 密钥明文；失败时补偿删除已创建的 one-api 记录，不留半绑定。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OneApiProvisioningServiceImpl implements OneApiProvisioningService {

    private final SysUserOneapiBindingDao bindingDao;
    private final OneApiProvisioningDao provisioningDao;
    private final OneApiProperties properties;
    private final SysUserDao sysUserDao;

    private static final SecureRandom RANDOM = new SecureRandom();
    private static final char[] PASSWORD_CHARS =
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789".toCharArray();

    @Override
    public void ensureProvisioned(Long sysUserId) {
        if (sysUserId == null) {
            throw new RenException("用户ID不能为空");
        }

        // 快路径：已有完整绑定直接返回
        SysUserOneapiBindingEntity existing = selectBinding(sysUserId);
        if (isComplete(existing)) {
            return;
        }

        String cipherKey = properties.getTokenCipherKey();
        if (StringUtils.isBlank(cipherKey)) {
            throw new RenException(ErrorCode.ONEAPI_TOKEN_CIPHER_KEY_NOT_CONFIGURED,
                    PayConstants.MSG_ONEAPI_TOKEN_CIPHER_KEY_NOT_CONFIGURED);
        }

        String displayName = resolveDisplayName(sysUserId);
        String oneapiUsername = PayConstants.ONEAPI_USERNAME_PREFIX + sysUserId;

        Long oneapiUserId = null;
        Long oneapiTokenId = null;
        boolean createdUser = false;
        boolean createdToken = false;

        try {
            // 1. 创建 / 复用 one-api user
            oneapiUserId = provisioningDao.findUserIdByUsername(oneapiUsername);
            if (oneapiUserId == null) {
                OneApiUserRow userRow = new OneApiUserRow();
                userRow.setUsername(oneapiUsername);
                userRow.setPassword(PasswordUtils.encode(randomPassword()));
                userRow.setDisplayName(displayName);
                userRow.setQuota(properties.getRegisterTrialQuota());
                try {
                    provisioningDao.insertUser(userRow);
                    oneapiUserId = userRow.getId();
                    createdUser = true;
                } catch (DuplicateKeyException e) {
                    oneapiUserId = provisioningDao.findUserIdByUsername(oneapiUsername);
                }
            }

            // 2. 创建 / 复用设备 token
            String tokenKey = null;
            oneapiTokenId = provisioningDao.findTokenIdByUserIdAndName(
                    oneapiUserId, PayConstants.ONEAPI_DEVICE_TOKEN_NAME);
            if (oneapiTokenId != null) {
                tokenKey = provisioningDao.findTokenKeyById(oneapiTokenId);
            }
            if (oneapiTokenId == null || StringUtils.isBlank(tokenKey)) {
                tokenKey = generateTokenKey();
                OneApiTokenRow tokenRow = new OneApiTokenRow();
                tokenRow.setUserId(oneapiUserId);
                tokenRow.setKey(tokenKey);
                tokenRow.setName(PayConstants.ONEAPI_DEVICE_TOKEN_NAME);
                tokenRow.setCreatedTime(System.currentTimeMillis() / 1000);
                tokenRow.setModels(PayConstants.ONEAPI_DEVICE_TOKEN_MODELS);
                provisioningDao.insertToken(tokenRow);
                oneapiTokenId = tokenRow.getId();
                createdToken = true;
            }

            // 3. 加密 token key 并写绑定
            String cipher = OneApiTokenCipher.encrypt(cipherKey, tokenKey);
            String fingerprint = OneApiTokenCipher.fingerprint(tokenKey);

            SysUserOneapiBindingEntity binding = new SysUserOneapiBindingEntity();
            binding.setSysUserId(sysUserId);
            binding.setOneapiUserId(oneapiUserId);
            binding.setOneapiUsername(displayName);
            binding.setOneapiTokenId(oneapiTokenId);
            binding.setOneapiTokenName(PayConstants.ONEAPI_DEVICE_TOKEN_NAME);
            binding.setOneapiTokenKeyCipher(cipher);
            binding.setOneapiTokenKeyFingerprint(fingerprint);
            try {
                bindingDao.insert(binding);
            } catch (DuplicateKeyException e) {
                // 并发下已被其他请求绑定：清理本次多创建的 token / user，视为成功
                cleanup(createdToken, oneapiTokenId, createdUser, oneapiUserId);
                return;
            }

            log.info("one-api 开户成功: sysUserId={}, oneapiUserId={}, oneapiTokenId={}, trialQuota={}",
                    sysUserId, oneapiUserId, oneapiTokenId, properties.getRegisterTrialQuota());
        } catch (RenException e) {
            cleanup(createdToken, oneapiTokenId, createdUser, oneapiUserId);
            throw e;
        } catch (Exception e) {
            cleanup(createdToken, oneapiTokenId, createdUser, oneapiUserId);
            log.error("one-api 开户失败: sysUserId={}, err={}", sysUserId, e.getMessage());
            throw new RenException(PayConstants.MSG_ONEAPI_PROVISION_FAILED);
        }
    }

    private SysUserOneapiBindingEntity selectBinding(Long sysUserId) {
        return bindingDao.selectOne(
                new QueryWrapper<SysUserOneapiBindingEntity>().eq("sys_user_id", sysUserId));
    }

    private boolean isComplete(SysUserOneapiBindingEntity binding) {
        return binding != null
                && binding.getOneapiUserId() != null
                && binding.getOneapiTokenId() != null
                && StringUtils.isNotBlank(binding.getOneapiTokenKeyCipher())
                && StringUtils.isNotBlank(binding.getOneapiTokenKeyFingerprint());
    }

    private String resolveDisplayName(Long sysUserId) {
        SysUserEntity sysUser = sysUserDao.selectById(sysUserId);
        return sysUser != null && StringUtils.isNotBlank(sysUser.getUsername())
                ? sysUser.getUsername()
                : String.valueOf(sysUserId);
    }

    private void cleanup(boolean createdToken, Long tokenId, boolean createdUser, Long userId) {
        if (createdToken && tokenId != null) {
            safeDelete(() -> provisioningDao.deleteToken(tokenId));
        }
        if (createdUser && userId != null) {
            safeDelete(() -> provisioningDao.deleteUser(userId));
        }
    }

    private void safeDelete(Runnable deleteAction) {
        try {
            deleteAction.run();
        } catch (Exception e) {
            log.warn("one-api 开户补偿清理失败: {}", e.getMessage());
        }
    }

    private String randomPassword() {
        StringBuilder sb = new StringBuilder(20);
        for (int i = 0; i < 20; i++) {
            sb.append(PASSWORD_CHARS[RANDOM.nextInt(PASSWORD_CHARS.length)]);
        }
        return sb.toString();
    }

    private String generateTokenKey() {
        // 与 one-api random.GenerateKey 类似：16 随机字符 + 32 位无横线 UUID，共 48 字符，唯一
        return RandomUtil.randomString(16) + IdUtil.fastSimpleUUID();
    }
}
