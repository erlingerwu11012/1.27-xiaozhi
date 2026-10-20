package xiaozhi.modules.device.controller;

import org.apache.commons.lang3.StringUtils;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.device.service.DeviceWsAuthService;
import xiaozhi.modules.device.service.impl.DeviceWsRevokeNotifyService;
import xiaozhi.modules.device.util.MacAddressUtils;
import xiaozhi.modules.device.vo.DeviceWsAuthStateVO;

/**
 * 服务间：查询 / 吊销设备 WSS 鉴权状态。
 * Shiro：/device/ws-auth/** → server（Bearer server.secret）。
 */
@Tag(name = "设备 WSS 鉴权状态")
@RestController
@RequestMapping("/device/ws-auth")
@RequiredArgsConstructor
public class DeviceWsAuthController {

    private final DeviceWsAuthService deviceWsAuthService;
    private final DeviceWsRevokeNotifyService revokeNotifyService;

    @GetMapping("/{mac}")
    @Operation(summary = "按 MAC 查询 WSS auth state（服务间）")
    public Result<DeviceWsAuthStateVO> getState(@PathVariable("mac") String mac) {
        if (StringUtils.isBlank(mac) || MacAddressUtils.toTokenDeviceId(mac) == null) {
            return new Result<DeviceWsAuthStateVO>().error("invalid device id");
        }
        DeviceWsAuthStateVO vo = deviceWsAuthService.getState(mac);
        if (vo == null) {
            return new Result<DeviceWsAuthStateVO>().error("ws auth state not found");
        }
        return new Result<DeviceWsAuthStateVO>().ok(vo);
    }

    @PostMapping("/{mac}/disable")
    @Operation(summary = "禁用设备 WSS 凭证（服务间或管理调用）")
    public Result<DeviceWsAuthStateVO> disable(@PathVariable("mac") String mac) {
        if (StringUtils.isBlank(mac) || MacAddressUtils.toTokenDeviceId(mac) == null) {
            return new Result<DeviceWsAuthStateVO>().error("invalid device id");
        }
        long ver = deviceWsAuthService.markDisabled(mac);
        String normalized = MacAddressUtils.toTokenDeviceId(mac);
        boolean syncOk = revokeNotifyService.tryNotify(normalized, ver, "disabled");
        DeviceWsAuthStateVO vo = deviceWsAuthService.getState(mac);
        if (vo == null) {
            vo = new DeviceWsAuthStateVO();
            vo.setDeviceId(normalized);
            vo.setCredentialVersion(ver);
            vo.setStatus("disabled");
        }
        // 不把 sync 失败伪造成功；状态以 DB 为准，通知结果仅日志
        if (!syncOk) {
            // status 已持久化；在线关闭为 pending
        }
        return new Result<DeviceWsAuthStateVO>().ok(vo);
    }
}
