package xiaozhi.modules.useridentity.controller;

import java.util.List;
import java.util.Map;

import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.security.user.SecurityUser;
import xiaozhi.modules.useridentity.dto.UserIdentityCreateDTO;
import xiaozhi.modules.useridentity.dto.UserIdentityDisplayNameDTO;
import xiaozhi.modules.useridentity.service.UserIdentityService;
import xiaozhi.modules.useridentity.service.AccountIdentityStateService;
import xiaozhi.modules.agent.service.AgentVoicePrintService;
import xiaozhi.modules.agent.vo.AgentVoicePrintVO;
import xiaozhi.modules.useridentity.vo.UserIdentityVO;

/** 统一用户档案与人脸/声纹显式绑定。 */
@Tag(name = "统一用户管理")
@RestController
@RequiredArgsConstructor
@RequestMapping("/user-identities")
public class UserIdentityController {
    private final UserIdentityService userIdentityService;
    private final AccountIdentityStateService identityState;
    private final AgentVoicePrintService voicePrintService;

    @GetMapping("/users")
    @RequiresPermissions("sys:role:normal")
    @Operation(summary = "当前账号的统一用户列表")
    public Result<List<UserIdentityVO>> list() {
        return new Result<List<UserIdentityVO>>().ok(userIdentityService.list(SecurityUser.getUserId()));
    }

    @PostMapping("/users")
    @RequiresPermissions("sys:role:normal")
    @Operation(summary = "创建成员；系统生成稳定 ID")
    public Result<UserIdentityVO> create(@RequestBody @Valid UserIdentityCreateDTO dto) {
        return new Result<UserIdentityVO>().ok(userIdentityService.create(
                SecurityUser.getUserId(), dto.getUserId(), dto.getDisplayName()));
    }

    @DeleteMapping("/users/{userId}")
    @RequiresPermissions("sys:role:normal")
    public Result<Void> delete(@PathVariable String userId) {
        identityState.deleteMember(SecurityUser.getUserId(),userId);
        return new Result<>();
    }

    @GetMapping("/voiceprints")
    @RequiresPermissions("sys:role:normal")
    public Result<List<AgentVoicePrintVO>> voices() {
        return new Result<List<AgentVoicePrintVO>>().ok(voicePrintService.list(SecurityUser.getUserId(),null));
    }

    @GetMapping("/internal/state/{accountId}")
    public Result<Map<String,Object>> state(@PathVariable Long accountId) {
        return new Result<Map<String,Object>>().ok(identityState.snapshot(accountId));
    }
    public record CapabilityRequest(Long accountId,String deviceId,Map<String,Object> versions,String firmwareVersion) {}
    @PostMapping("/internal/capability")
    public Result<Void> capability(@RequestBody CapabilityRequest request) {
        if(request.accountId()==null || request.deviceId()==null || request.deviceId().length()>64 || request.versions()==null || request.firmwareVersion()!=null && request.firmwareVersion().length()>64)throw new xiaozhi.common.exception.RenException("能力声明无效");
        identityState.reportCapability(request.accountId(),request.deviceId(),request.versions(),request.firmwareVersion());return new Result<>();
    }
    public record CleanupAcknowledgement(Long accountId,String deviceId,String cleanupId) {}
    @PostMapping("/internal/cleanup-ack")
    public Result<Void> cleanupAck(@RequestBody CleanupAcknowledgement request) {
        identityState.acknowledgeCleanup(request.accountId(),request.deviceId(),request.cleanupId());return new Result<>();
    }

    @PutMapping("/users/{userId}/display-name")
    @RequiresPermissions("sys:role:normal")
    @Operation(summary = "修改统一用户显示名")
    public Result<UserIdentityVO> updateDisplayName(@PathVariable String userId,
            @RequestBody @Valid UserIdentityDisplayNameDTO dto) {
        return new Result<UserIdentityVO>().ok(userIdentityService.updateDisplayName(
                SecurityUser.getUserId(), userId, dto.getDisplayName()));
    }

    @PostMapping("/users/{userId}/faces/{faceProfileId}")
    @RequiresPermissions("sys:role:normal")
    @Operation(summary = "绑定已有 face-api profile 到统一用户")
    public Result<Void> bindFace(@PathVariable String userId, @PathVariable String faceProfileId) {
        userIdentityService.bindFace(SecurityUser.getUserId(), userId, faceProfileId);
        return new Result<>();
    }

    @DeleteMapping("/users/{userId}/faces/{faceProfileId}")
    @RequiresPermissions("sys:role:normal")
    @Operation(summary = "解绑人脸 profile，不删除人脸数据")
    public Result<Void> unbindFace(@PathVariable String userId, @PathVariable String faceProfileId) {
        userIdentityService.unbindFace(SecurityUser.getUserId(), userId, faceProfileId);
        return new Result<>();
    }

    @PostMapping("/users/{userId}/voiceprints/{voiceprintId}")
    @RequiresPermissions("sys:role:normal")
    @Operation(summary = "绑定已有声纹到统一用户")
    public Result<Void> bindVoiceprint(@PathVariable String userId, @PathVariable String voiceprintId) {
        userIdentityService.bindVoiceprint(SecurityUser.getUserId(), userId, voiceprintId);
        return new Result<>();
    }

    @DeleteMapping("/users/{userId}/voiceprints/{voiceprintId}")
    @RequiresPermissions("sys:role:normal")
    @Operation(summary = "解绑声纹，不删除声纹向量")
    public Result<Void> unbindVoiceprint(@PathVariable String userId, @PathVariable String voiceprintId) {
        userIdentityService.unbindVoiceprint(SecurityUser.getUserId(), userId, voiceprintId);
        return new Result<>();
    }

    @GetMapping("/unbound/voiceprints")
    @RequiresPermissions("sys:role:normal")
    @Operation(summary = "查询未绑定的历史声纹")
    public Result<List<String>> unboundVoiceprints(@RequestParam(required = false) String agentId) {
        return new Result<List<String>>().ok(userIdentityService.unboundVoiceprintIds(
                SecurityUser.getUserId(), agentId));
    }

    @GetMapping("/face-bindings")
    @RequiresPermissions("sys:role:normal")
    @Operation(summary = "查询当前账号人脸绑定，用于管理页筛选未绑定人脸")
    public Result<List<String>> faceBindings() {
        return new Result<List<String>>().ok(userIdentityService.boundFaceProfileIds(SecurityUser.getUserId()));
    }

    @GetMapping("/device-directory/{accountId}")
    @Operation(summary = "供 xiaozhi-server 调用的统一用户目录（服务密钥鉴权）")
    public Result<List<Map<String, Object>>> deviceDirectory(@PathVariable Long accountId) {
        return new Result<List<Map<String, Object>>>().ok(userIdentityService.getDeviceDirectory(accountId));
    }
}
