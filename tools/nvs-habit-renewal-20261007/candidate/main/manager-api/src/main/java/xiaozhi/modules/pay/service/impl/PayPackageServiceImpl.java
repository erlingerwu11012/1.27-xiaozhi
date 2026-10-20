package xiaozhi.modules.pay.service.impl;

import java.util.List;

import org.springframework.stereotype.Service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.service.impl.BaseServiceImpl;
import xiaozhi.common.utils.ConvertUtils;
import xiaozhi.modules.pay.dao.PayPackageDao;
import xiaozhi.modules.pay.entity.PayPackageEntity;
import xiaozhi.modules.pay.service.PayPackageService;
import xiaozhi.modules.pay.vo.PayPackageVO;

@Slf4j
@Service
@RequiredArgsConstructor
public class PayPackageServiceImpl extends BaseServiceImpl<PayPackageDao, PayPackageEntity>
        implements PayPackageService {

    @Override
    public List<PayPackageVO> listEnabled() {
        QueryWrapper<PayPackageEntity> wrapper = new QueryWrapper<>();
        wrapper.eq("enabled", 1).orderByAsc("sort").orderByAsc("id");
        List<PayPackageEntity> list = baseDao.selectList(wrapper);
        return ConvertUtils.sourceToTarget(list, PayPackageVO.class);
    }
}
