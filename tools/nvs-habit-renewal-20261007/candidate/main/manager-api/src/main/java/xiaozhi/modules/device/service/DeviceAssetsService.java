package xiaozhi.modules.device.service;

import org.springframework.web.multipart.MultipartFile;

import java.util.List;

import xiaozhi.modules.device.dto.DeviceAssetUploadDTO;
import xiaozhi.modules.device.vo.DeviceAssetCheckUpdateVO;
import xiaozhi.modules.device.vo.DeviceAssetListItemVO;

/**
 * 设备资源（表情包/壁纸）上传与待更新查询
 */
public interface DeviceAssetsService {

    /**
     * 上传图片并写入 ai_device_assets，自动生成版本号
     *
     * @param deviceId 设备ID
     * @param fileType emoji / wallpaper
     * @param file     图片文件
     * @return 文件路径与版本号
     */
    DeviceAssetUploadDTO uploadImage(String deviceId, String fileType, MultipartFile file);

    /**
     * 按设备查询已上传资源列表（供前端展示）
     *
     * @param deviceId 设备ID
     * @return 资源列表，按版本倒序
     */
    List<DeviceAssetListItemVO> listByDevice(String deviceId);

    /**
     * 供 Python 后端查询：该设备是否有待更新的资源（可传设备当前版本，服务端对比最新 version）
     *
     * @param deviceId    设备ID
     * @param currentVersion 设备当前资源版本（可选，不传则仅返回最新资源信息）
     * @return 是否有更新 + 最新资源列表
     */
    DeviceAssetCheckUpdateVO checkUpdate(String deviceId, Integer currentVersion);

    /**
     * 将该设备的资源（emoji + wallpaper）打包为 SPIFFS 镜像 .bin 文件（输出到 uploads/temp/{deviceId}_assets.bin）
     *
     * @param deviceId 设备ID
     * @return 生成好的 bin 文件的完整下载 URL（若未配置 base-url 则返回相对路径）
     */
    String createSpiffsImage(String deviceId);

    /**
     * 同步资源到设备：先打包生成 bin，再通过 WebSocket 向设备推送 update_assets 指令
     *
     * @param deviceId 设备ID
     * @return 打包后的下载路径（相对 uploads 的路径）
     */
    String syncAssets(String deviceId);
}
