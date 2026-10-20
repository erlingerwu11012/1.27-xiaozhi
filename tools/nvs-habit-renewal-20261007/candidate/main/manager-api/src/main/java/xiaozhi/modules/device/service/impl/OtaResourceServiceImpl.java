package xiaozhi.modules.device.service.impl;

import java.util.Arrays;
import java.util.Map;

import org.springframework.stereotype.Service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;

import io.micrometer.common.util.StringUtils;
import xiaozhi.common.page.PageData;
import xiaozhi.common.service.impl.BaseServiceImpl;
import xiaozhi.modules.device.dao.OtaResourceDao;
import xiaozhi.modules.device.entity.OtaResourceEntity;
import xiaozhi.modules.device.service.OtaResourceService;

/**
 * OTA 资源包管理（表情包、壁纸等）
 */
@Service
public class OtaResourceServiceImpl extends BaseServiceImpl<OtaResourceDao, OtaResourceEntity> implements OtaResourceService {

    @Override
    public PageData<OtaResourceEntity> page(Map<String, Object> params) {
        IPage<OtaResourceEntity> page = baseDao.selectPage(
                getPage(params, "update_date", true),
                getWrapper(params));
        return new PageData<>(page.getRecords(), page.getTotal());
    }

    private QueryWrapper<OtaResourceEntity> getWrapper(Map<String, Object> params) {
        String resourceName = (String) params.get("resourceName");
        String resourceType = (String) params.get("resourceType");

        QueryWrapper<OtaResourceEntity> wrapper = new QueryWrapper<>();
        wrapper.like(StringUtils.isNotBlank(resourceName), "resource_name", resourceName)
               .eq(StringUtils.isNotBlank(resourceType), "resource_type", resourceType);

        return wrapper;
    }

    @Override
    public boolean save(OtaResourceEntity entity) {
        // 目前简单插入；如需“同类型+版本只保留一条”，可在后续按业务调整
        return baseDao.insert(entity) > 0;
    }

    @Override
    public void update(OtaResourceEntity entity) {
        baseDao.updateById(entity);
    }

    @Override
    public void delete(String[] ids) {
        baseDao.deleteBatchIds(Arrays.asList(ids));
    }
}

