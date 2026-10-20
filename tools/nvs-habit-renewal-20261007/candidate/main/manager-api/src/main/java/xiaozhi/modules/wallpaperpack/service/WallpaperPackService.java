package xiaozhi.modules.wallpaperpack.service;

import java.util.List;

import org.springframework.web.multipart.MultipartFile;
import org.springframework.http.ResponseEntity;

import xiaozhi.modules.wallpaperpack.dto.WallpaperPackPublishDTO;
import xiaozhi.modules.wallpaperpack.dto.WallpaperPackUpdateDTO;
import xiaozhi.modules.wallpaperpack.entity.WallpaperPackEntity;
import xiaozhi.modules.wallpaperpack.vo.WallpaperPackCatalogItemVO;
import xiaozhi.modules.wallpaperpack.vo.WallpaperPackInspectVO;

public interface WallpaperPackService {

    WallpaperPackEntity publish(Long adminUserId, WallpaperPackPublishDTO meta, MultipartFile spineBin,
            MultipartFile previewImage, MultipartFile previewVideo);

    WallpaperPackInspectVO inspect(MultipartFile spineBin);

    ResponseEntity<byte[]> servePublishedPreview(String packId, String kind, String rangeHeader);

    WallpaperPackEntity updateMeta(Long adminUserId, String packId, WallpaperPackUpdateDTO dto);

    WallpaperPackEntity disable(Long adminUserId, String packId);

    List<WallpaperPackCatalogItemVO> catalogPublished();

    WallpaperPackCatalogItemVO getPublished(String packId);

    WallpaperPackCatalogItemVO toCatalogItem(WallpaperPackEntity entity);

    WallpaperPackEntity requirePublished(String packId);

    WallpaperPackEntity getByPackId(String packId);

    byte[] readPackBytes(WallpaperPackEntity pack);
}
