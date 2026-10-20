package xiaozhi.modules.rolepack.service;

import java.util.List;

import org.springframework.web.multipart.MultipartFile;
import org.springframework.http.ResponseEntity;

import xiaozhi.modules.rolepack.dto.RolePackPublishDTO;
import xiaozhi.modules.rolepack.dto.RolePackUpdateDTO;
import xiaozhi.modules.rolepack.entity.RolePackEntity;
import xiaozhi.modules.rolepack.vo.RolePackCatalogItemVO;
import xiaozhi.modules.rolepack.vo.RolePackInspectVO;

public interface RolePackService {

    RolePackEntity publish(Long adminUserId, RolePackPublishDTO meta, MultipartFile spineBin,
            MultipartFile previewImage, MultipartFile previewVideo);

    RolePackInspectVO inspect(MultipartFile spineBin);

    ResponseEntity<byte[]> servePublishedPreview(String packId, String kind, String rangeHeader);

    RolePackEntity updateMeta(Long adminUserId, String packId, RolePackUpdateDTO dto);

    RolePackEntity disable(Long adminUserId, String packId);

    List<RolePackCatalogItemVO> catalogPublished();

    RolePackCatalogItemVO getPublished(String packId);

    RolePackCatalogItemVO toCatalogItem(RolePackEntity entity);

    RolePackEntity requirePublished(String packId);

    RolePackEntity getByPackId(String packId);

    byte[] readPackBytes(RolePackEntity pack);
}
