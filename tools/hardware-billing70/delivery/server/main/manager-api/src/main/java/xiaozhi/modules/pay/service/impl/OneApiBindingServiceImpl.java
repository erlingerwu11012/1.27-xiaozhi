package xiaozhi.modules.pay.service.impl;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.ErrorCode;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.pay.config.OneApiProperties;
import xiaozhi.modules.pay.constant.PayConstants;
import xiaozhi.modules.pay.dao.SysUserOneapiBindingDao;
import xiaozhi.modules.pay.entity.SysUserOneapiBindingEntity;
import xiaozhi.modules.pay.service.OneApiBindingService;
import xiaozhi.modules.pay.service.OneApiProvisioningService;
import xiaozhi.modules.pay.util.OneApiTokenCipher;
import xiaozhi.modules.pay.vo.OneApiDeviceTokenVO;

/**
 * one-api 设备 token 解析实现。全程不打印 token 明文。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class OneApiBindingServiceImpl implements OneApiBindingService {

    @org.springframework.beans.factory.annotation.Value("${hardware.billing.enabled:false}")
    private boolean hardwareBillingEnabled;

    private final SysUserOneapiBindingDao bindingDao;
    private final OneApiProperties properties;
    private final OneApiProvisioningService provisioningService;
    private final xiaozhi.modules.pay.dao.OneApiProvisioningDao provisioningDao;

    @Override
    public OneApiDeviceTokenVO resolveDeviceToken(Long sysUserId) {
        SysUserOneapiBindingEntity binding = bindingDao.selectOne(
                new QueryWrapper<SysUserOneapiBindingEntity>().eq("sys_user_id", sysUserId));
        if (binding == null) {
            // 只读确认是否需要兜底：未绑定则尝试开通（幂等），失败由 ensureProvisioned 抛异常 fail-closed
            provisioningService.ensureProvisioned(sysUserId);
            binding = bindingDao.selectOne(
                    new QueryWrapper<SysUserOneapiBindingEntity>().eq("sys_user_id", sysUserId));
        }
        if (binding == null) {
            throw new RenException(ErrorCode.ONEAPI_BINDING_NOT_FOUND, PayConstants.MSG_ONEAPI_BINDING_NOT_FOUND);
        }

        if (StringUtils.isBlank(binding.getOneapiTokenKeyCipher())) {
            log.warn("设备 token 未配置: sysUserId={}, oneapiUserId={}",
                    sysUserId, binding.getOneapiUserId());
            throw new RenException(ErrorCode.ONEAPI_DEVICE_TOKEN_NOT_CONFIGURED, PayConstants.MSG_ONEAPI_DEVICE_TOKEN_NOT_CONFIGURED);
        }

        String cipherKey = properties.getTokenCipherKey();
        if (StringUtils.isBlank(cipherKey)) {
            log.error("one-api 设备 token 加密密钥未配置");
            throw new RenException(ErrorCode.ONEAPI_TOKEN_CIPHER_KEY_NOT_CONFIGURED, PayConstants.MSG_ONEAPI_TOKEN_CIPHER_KEY_NOT_CONFIGURED);
        }

        String tokenKey;
        try {
            tokenKey = OneApiTokenCipher.decrypt(cipherKey, binding.getOneapiTokenKeyCipher());
        } catch (Exception e) {
            // 不打印密文与明文，仅记录失败原因
            log.error("设备 token 解密失败: sysUserId={}, err={}", sysUserId, e.getMessage());
            throw new RenException("one-api 设备 token 解密失败");
        }

        OneApiDeviceTokenVO vo = new OneApiDeviceTokenVO();
        if(binding.getOneapiTokenId()!=null) provisioningDao.enableMemoryForOwnedDeviceToken(binding.getOneapiTokenId(),binding.getOneapiUserId());
        if(hardwareBillingEnabled && binding.getOneapiTokenId()!=null) {
            for(String requiredModel:java.util.List.of("qwen-plus","qwen3-vl-flash","qwen3-asr-flash-realtime","qwen-audio-3.0-tts-plus"))
                provisioningDao.enableHardwareModelForOwnedDeviceToken(binding.getOneapiTokenId(),binding.getOneapiUserId(),requiredModel);
        }
        vo.setToken(tokenKey);
        vo.setOneapiUserId(binding.getOneapiUserId());
        vo.setFingerprint(binding.getOneapiTokenKeyFingerprint());
        return vo;
    }
}
