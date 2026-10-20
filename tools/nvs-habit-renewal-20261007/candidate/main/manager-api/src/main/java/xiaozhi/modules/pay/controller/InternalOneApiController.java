package xiaozhi.modules.pay.controller;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

import org.apache.commons.lang3.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.ErrorCode;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.pay.config.OneApiProperties;
import xiaozhi.modules.pay.constant.PayConstants;
import xiaozhi.modules.pay.service.OneApiBindingService;
import xiaozhi.modules.pay.vo.OneApiDeviceTokenVO;

/**
 * 内部服务间接口：为 aimi-cn-gateway 提供按 sys_user 路由的 one-api 设备 token。
 *
 * 鉴权：请求头 X-Realecho-Internal-Token 必须与配置的服务间密钥一致（常量时间比较）。
 * 注意：Shiro 已将 /internal/** 设为 anon，本控制器自行鉴权。
 */
@Slf4j
@RestController
@RequestMapping("/internal/oneapi")
@RequiredArgsConstructor
public class InternalOneApiController {

    private final OneApiBindingService bindingService;
    private final OneApiProperties properties;

    @GetMapping("/device-token/{sysUserId}")
    public Result<OneApiDeviceTokenVO> deviceToken(
            @PathVariable("sysUserId") Long sysUserId,
            @RequestHeader(value = "X-Realecho-Internal-Token", required = false) String internalToken) {

        if (!isAuthorized(internalToken)) {
            log.warn("内部接口鉴权失败: path=/internal/oneapi/device-token, sysUserId={}", sysUserId);
            return new Result<OneApiDeviceTokenVO>().error(ErrorCode.UNAUTHORIZED, PayConstants.MSG_ONEAPI_INTERNAL_TOKEN_INVALID);
        }

        OneApiDeviceTokenVO vo = bindingService.resolveDeviceToken(sysUserId);
        return new Result<OneApiDeviceTokenVO>().ok(vo);
    }

    private boolean isAuthorized(String provided) {
        String expected = properties.getInternalToken();
        if (StringUtils.isBlank(expected)) {
            log.error(PayConstants.MSG_ONEAPI_INTERNAL_TOKEN_NOT_CONFIGURED);
            return false;
        }
        if (StringUtils.isBlank(provided)) {
            return false;
        }
        return MessageDigest.isEqual(
                expected.getBytes(StandardCharsets.UTF_8),
                provided.getBytes(StandardCharsets.UTF_8));
    }
}
