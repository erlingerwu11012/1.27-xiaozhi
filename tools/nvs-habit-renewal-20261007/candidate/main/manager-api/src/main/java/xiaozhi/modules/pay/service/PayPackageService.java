package xiaozhi.modules.pay.service;

import java.util.List;

import xiaozhi.common.service.BaseService;
import xiaozhi.modules.pay.entity.PayPackageEntity;
import xiaozhi.modules.pay.vo.PayPackageVO;

/**
 * 支付套餐 Service
 */
public interface PayPackageService extends BaseService<PayPackageEntity> {

    /**
     * 查询所有启用的套餐，按排序权重升序
     */
    List<PayPackageVO> listEnabled();
}
