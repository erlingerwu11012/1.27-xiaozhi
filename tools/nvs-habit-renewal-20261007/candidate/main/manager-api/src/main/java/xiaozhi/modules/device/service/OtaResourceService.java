package xiaozhi.modules.device.service;

import java.util.Map;

import xiaozhi.common.page.PageData;
import xiaozhi.common.service.BaseService;
import xiaozhi.modules.device.entity.OtaResourceEntity;

/**
 * OTA 资源包管理（表情包、壁纸等）
 */
public interface OtaResourceService extends BaseService<OtaResourceEntity> {

    /**
     * 分页查询资源包
     */
    PageData<OtaResourceEntity> page(Map<String, Object> params);

    /**
     * 保存资源包（如存在相同类型+版本可按需要做覆盖策略）
     */
    boolean save(OtaResourceEntity entity);

    /**
     * 更新资源包元数据
     */
    void update(OtaResourceEntity entity);

    /**
     * 批量删除资源包
     */
    void delete(String[] ids);
}

