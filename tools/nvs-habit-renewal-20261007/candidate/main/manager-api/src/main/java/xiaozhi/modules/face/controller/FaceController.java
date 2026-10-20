package xiaozhi.modules.face.controller;

import java.util.Map;

import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.face.service.FaceProxyService;

/**
 * 网页人脸管理入口：需 oauth2 登录；服务端代理 face-api，不向浏览器暴露 face JWT。
 */
@Tag(name = "人脸用户管理")
@RestController
@RequiredArgsConstructor
@RequestMapping("/face")
public class FaceController {

    private final FaceProxyService faceProxyService;

    @GetMapping("/profiles")
    @Operation(summary = "用户列表（管理页默认含草稿；首次访问会确保默认主人）")
    public Result<Object> list(
            @RequestParam(value = "include_draft", defaultValue = "true") boolean includeDraft) {
        return new Result<>().ok(faceProxyService.listProfiles(includeDraft));
    }

    @PostMapping("/accounts/ensure-owner")
    @Operation(summary = "确保当前登录用户账号存在默认主人 usr_*")
    public Result<Object> ensureOwner() {
        return new Result<>().ok(faceProxyService.ensureDefaultOwner());
    }

    @GetMapping("/profiles/{userId}")
    @Operation(summary = "用户详情")
    public Result<Object> get(@PathVariable("userId") String userId) {
        return new Result<>().ok(faceProxyService.getProfile(userId));
    }

    @PostMapping("/profiles")
    @Operation(summary = "创建草稿用户")
    public Result<Object> create(@RequestBody Map<String, Object> body) {
        return new Result<>().ok(faceProxyService.createProfile(body));
    }

    @PostMapping("/profiles/{userId}/faces")
    @Operation(summary = "草稿上传人脸照片")
    public Result<Object> uploadFace(
            @PathVariable("userId") String userId,
            @RequestParam("image") MultipartFile image) {
        return new Result<>().ok(faceProxyService.uploadFace(userId, image));
    }

    @PostMapping("/profiles/{userId}/activate")
    @Operation(summary = "确认启用用户（冻结姓名与人脸）")
    public Result<Object> activate(@PathVariable("userId") String userId) {
        return new Result<>().ok(faceProxyService.activate(userId));
    }

    @DeleteMapping("/profiles/{userId}")
    @Operation(summary = "按 user_id 删除用户")
    public Result<Object> delete(@PathVariable("userId") String userId) {
        return new Result<>().ok(faceProxyService.deleteProfile(userId));
    }

    @GetMapping("/enrollment/sessions")
    @Operation(summary = "待命名的设备采集草稿列表")
    public Result<Object> listEnrollmentSessions() {
        return new Result<>().ok(faceProxyService.listEnrollmentSessions());
    }

    @GetMapping("/enrollment/sessions/{sessionId}/preview")
    @Operation(summary = "草稿预览图（需登录；禁止静态直链）")
    public ResponseEntity<byte[]> enrollmentPreview(@PathVariable("sessionId") String sessionId) {
        byte[] body = faceProxyService.enrollmentPreview(sessionId);
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.IMAGE_JPEG);
        headers.setCacheControl("no-store");
        headers.set("X-Content-Type-Options", "nosniff");
        return ResponseEntity.ok().headers(headers).body(body);
    }

    @PostMapping("/enrollment/sessions/{sessionId}/confirm")
    @Operation(summary = "确认启用：命名并创建 active usr_*")
    public Result<Object> confirmEnrollment(
            @PathVariable("sessionId") String sessionId,
            @RequestBody Map<String, Object> body) {
        return new Result<>().ok(faceProxyService.confirmEnrollment(sessionId, body));
    }

    @DeleteMapping("/enrollment/sessions/{sessionId}")
    @Operation(summary = "丢弃设备采集草稿")
    public Result<Object> discardEnrollment(@PathVariable("sessionId") String sessionId) {
        return new Result<>().ok(faceProxyService.discardEnrollment(sessionId));
    }
}
