package xiaozhi.modules.device.controller;

import org.apache.commons.lang3.StringUtils;
import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import java.util.List;

import xiaozhi.common.utils.Result;
import xiaozhi.modules.device.dto.DeviceAssetUploadDTO;
import xiaozhi.modules.device.service.DeviceAssetsService;
import xiaozhi.modules.device.vo.DeviceAssetCheckUpdateVO;
import xiaozhi.modules.device.vo.DeviceAssetListItemVO;

@Tag(name = "设备管理", description = "表情包与壁纸上传")
@RestController
@RequestMapping("/device/assets")
@RequiredArgsConstructor
public class FileController {

    private final DeviceAssetsService deviceAssetsService;

    @PostMapping("/upload")
    @Operation(summary = "上传图片（表情包/壁纸）")
    @RequiresPermissions("sys:role:normal")
    public Result<DeviceAssetUploadDTO> uploadImage(
            @Parameter(description = "设备ID", required = true) @RequestParam("device_id") String deviceId,
            @Parameter(description = "类型：emoji-表情包 / wallpaper-壁纸", required = true) @RequestParam("file_type") String fileType,
            @Parameter(description = "图片文件", required = true) @RequestParam("file") MultipartFile file) {
        if (StringUtils.isBlank(deviceId)) {
            return new Result<DeviceAssetUploadDTO>().error("设备ID不能为空");
        }
        if (StringUtils.isBlank(fileType)) {
            return new Result<DeviceAssetUploadDTO>().error("file_type 不能为空");
        }
        DeviceAssetUploadDTO dto = deviceAssetsService.uploadImage(deviceId, fileType, file);
        return new Result<DeviceAssetUploadDTO>().ok(dto);
    }

    @GetMapping("/list")
    @Operation(summary = "按设备查询已上传资源列表（供前端展示）")
    @RequiresPermissions("sys:role:normal")
    public Result<List<DeviceAssetListItemVO>> list(
            @Parameter(description = "设备ID", required = true) @RequestParam("device_id") String deviceId) {
        List<DeviceAssetListItemVO> list = deviceAssetsService.listByDevice(deviceId);
        return new Result<List<DeviceAssetListItemVO>>().ok(list);
    }

    @PostMapping("/sync-assets")
    @Operation(summary = "同步资源到设备：打包为 SPIFFS 镜像并返回下载地址")
    @RequiresPermissions("sys:role:normal")
    public Result<String> syncAssets(
            @Parameter(description = "设备ID", required = true) @RequestParam("device_id") String deviceId) {
        if (StringUtils.isBlank(deviceId)) {
            return new Result<String>().error("设备ID不能为空");
        }
        String downloadPath = deviceAssetsService.syncAssets(deviceId);
        return new Result<String>().ok(downloadPath);
    }

    @GetMapping("/check-update")
    @Operation(summary = "查询设备是否有待更新的资源（供 Python 后端轮询）")
    public Result<DeviceAssetCheckUpdateVO> checkUpdate(
            @Parameter(description = "设备ID", required = true) @RequestParam("device_id") String deviceId,
            @Parameter(description = "设备当前资源版本号，不传则仅返回最新资源列表") @RequestParam(value = "current_version", required = false) Integer currentVersion) {
        DeviceAssetCheckUpdateVO vo = deviceAssetsService.checkUpdate(deviceId, currentVersion);
        return new Result<DeviceAssetCheckUpdateVO>().ok(vo);
    }
}
