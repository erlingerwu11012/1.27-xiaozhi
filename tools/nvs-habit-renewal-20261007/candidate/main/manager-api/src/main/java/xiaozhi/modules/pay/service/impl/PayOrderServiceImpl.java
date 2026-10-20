package xiaozhi.modules.pay.service.impl;

import java.util.Map;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.page.PageData;
import xiaozhi.common.service.impl.BaseServiceImpl;
import xiaozhi.common.utils.ConvertUtils;
import xiaozhi.modules.pay.config.PayProperties;
import xiaozhi.modules.pay.constant.PayConstants;
import xiaozhi.modules.pay.dao.PayOrderDao;
import xiaozhi.modules.pay.dao.PayPackageDao;
import xiaozhi.modules.pay.dto.OrderCreateDTO;
import xiaozhi.modules.pay.entity.PayOrderEntity;
import xiaozhi.modules.pay.entity.PayPackageEntity;
import xiaozhi.modules.pay.service.AlipayService;
import xiaozhi.modules.pay.service.MockPayService;
import xiaozhi.modules.pay.service.OneApiProvisioningService;
import xiaozhi.modules.pay.service.PayOrderService;
import xiaozhi.modules.pay.service.WechatPayService;
import xiaozhi.modules.pay.vo.PayOrderVO;

@Slf4j
@Service
@RequiredArgsConstructor
public class PayOrderServiceImpl extends BaseServiceImpl<PayOrderDao, PayOrderEntity>
        implements PayOrderService {

    private final PayPackageDao payPackageDao;
    private final WechatPayService wechatPayService;
    private final AlipayService alipayService;
    private final MockPayService mockPayService;
    private final PayProperties payProperties;
    private final OneApiProvisioningService oneApiProvisioningService;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public PayOrderVO create(Long userId, OrderCreateDTO dto) {
        String channel = dto.getChannel() == null ? null : dto.getChannel().trim();
        if (!isSupportedChannel(channel)) {
            throw new RenException("不支持的支付渠道");
        }
        // mock 渠道：仅在开关开启时允许
        if (PayConstants.CHANNEL_MOCK.equals(channel) && !mockPayService.isEnabled()) {
            throw new RenException(PayConstants.MSG_MOCK_DISABLED);
        }
        // 非 mock 渠道必须已配置真实支付参数
        if (PayConstants.CHANNEL_WECHAT.equals(channel) && !wechatPayService.isConfigured()) {
            throw new RenException(PayConstants.MSG_CHANNEL_NOT_CONFIGURED);
        }
        if (PayConstants.CHANNEL_ALIPAY.equals(channel) && !alipayService.isConfigured()) {
            throw new RenException(PayConstants.MSG_ALIPAY_NOT_CONFIGURED);
        }

        PayPackageEntity pkg = payPackageDao.selectById(dto.getPackageId());
        if (pkg == null) {
            throw new RenException("套餐不存在");
        }
        if (pkg.getEnabled() == null || pkg.getEnabled() != 1) {
            throw new RenException("套餐已下架");
        }

        // 未开户不建单：确保 one-api 计费账户已开通（老用户在此补偿兜底）
        oneApiProvisioningService.ensureProvisioned(userId);

        // 创建订单，记录套餐价格与额度快照，避免套餐后续修改影响历史订单
        PayOrderEntity order = new PayOrderEntity();
        order.setOutTradeNo(PayConstants.generateOutTradeNo());
        order.setUserId(userId);
        order.setPackageId(pkg.getId());
        order.setPackageCode(pkg.getPackageCode());
        order.setPackageName(pkg.getName());
        order.setAmountCents(pkg.getAmountCents());
        order.setQuotaPoints(pkg.getQuotaPoints());
        order.setChannel(channel);
        order.setStatus(PayConstants.STATUS_PENDING);
        baseDao.insert(order);

        PayOrderVO vo = ConvertUtils.sourceToTarget(order, PayOrderVO.class);

        // alipay 渠道：生成电脑网站支付表单，前端渲染后跳转支付宝
        if (PayConstants.CHANNEL_ALIPAY.equals(channel)) {
            vo.setPayForm(alipayService.createPagePay(order));
        }

        return vo;
    }

    @Override
    public PayOrderVO queryByOrderNo(Long userId, String orderNo) {
        PayOrderEntity order = getOwnedOrder(userId, orderNo);
        return ConvertUtils.sourceToTarget(order, PayOrderVO.class);
    }

    @Override
    public PageData<PayOrderVO> page(Long userId, Map<String, Object> params) {
        IPage<PayOrderEntity> page = baseDao.selectPage(
                getPage(params, "id", false),
                new QueryWrapper<PayOrderEntity>().eq("user_id", userId));
        return getPageData(page, PayOrderVO.class);
    }

    /**
     * 查询订单并校验归属
     */
    private PayOrderEntity getOwnedOrder(Long userId, String orderNo) {
        PayOrderEntity order = baseDao.selectOne(new QueryWrapper<PayOrderEntity>().eq("out_trade_no", orderNo));
        if (order == null) {
            throw new RenException("订单不存在");
        }
        if (!userId.equals(order.getUserId())) {
            throw new RenException("无权查看该订单");
        }
        return order;
    }

    private boolean isSupportedChannel(String channel) {
        return PayConstants.CHANNEL_MOCK.equals(channel)
                || PayConstants.CHANNEL_WECHAT.equals(channel)
                || PayConstants.CHANNEL_ALIPAY.equals(channel);
    }
}
