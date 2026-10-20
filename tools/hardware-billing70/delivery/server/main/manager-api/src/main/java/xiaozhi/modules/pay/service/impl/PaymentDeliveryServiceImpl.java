package xiaozhi.modules.pay.service.impl;

import java.util.Date;

import org.springframework.stereotype.Service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.utils.ConvertUtils;
import xiaozhi.modules.pay.client.OneApiClient;
import xiaozhi.modules.pay.constant.PayConstants;
import xiaozhi.modules.pay.dao.OneapiRechargeLogDao;
import xiaozhi.modules.pay.dao.PayOrderDao;
import xiaozhi.modules.pay.dao.SysUserOneapiBindingDao;
import xiaozhi.modules.pay.entity.OneapiRechargeLogEntity;
import xiaozhi.modules.pay.entity.PayOrderEntity;
import xiaozhi.modules.pay.entity.SysUserOneapiBindingEntity;
import xiaozhi.modules.pay.service.OneApiProvisioningService;
import xiaozhi.modules.pay.service.PaymentDeliveryService;
import xiaozhi.modules.pay.service.UserQuotaService;
import xiaozhi.modules.pay.vo.PayOrderVO;

/**
 * 统一发货服务：所有渠道（alipay/mock/wechat）支付成功后共用。
 *
 * 幂等与不重试约定：
 * - 已 delivered 直接返回；
 * - oneapi_recharge_log 已有 success 记录时补偿订单为 delivered，不重复 topup；
 * - 已 paid（含 recharge pending/failed）直接返回，不自动重试 topup，等待人工处理。
 * 不使用整体事务：外部 topup 调用后需立即落库各状态，失败时订单仍保留 paid。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PaymentDeliveryServiceImpl implements PaymentDeliveryService {

    private final PayOrderDao payOrderDao;
    private final UserQuotaService userQuotaService;
    private final OneApiClient oneApiClient;
    private final SysUserOneapiBindingDao bindingDao;
    private final OneapiRechargeLogDao rechargeLogDao;
    private final OneApiProvisioningService oneApiProvisioningService;
    @org.springframework.beans.factory.annotation.Autowired
    private xiaozhi.modules.pay.service.HardwareWalletRechargeService hardwareRecharge;

    @Override
    public PayOrderVO deliver(String orderNo, String tradeNo) {
        PayOrderEntity order = payOrderDao.selectOne(
                new QueryWrapper<PayOrderEntity>().eq("out_trade_no", orderNo));
        if (order == null) {
            throw new RenException("订单不存在");
        }
        Long userId = order.getUserId();

        // 幂等1：已发货直接返回
        if (PayConstants.STATUS_DELIVERED.equals(order.getStatus())) {
            return ConvertUtils.sourceToTarget(order, PayOrderVO.class);
        }

        // 幂等2：充值流水已有 success，补偿订单为 delivered 并返回，不重复 topup
        Long successCount = rechargeLogDao.selectCount(new QueryWrapper<OneapiRechargeLogEntity>()
                .eq("order_no", orderNo)
                .eq("status", PayConstants.RECHARGE_LOG_SUCCESS));
        if (successCount != null && successCount > 0) {
            // 补偿本地账本：进程可能在写入成功充值流水后、发放本地额度前中断，
            // 导致 user_quota 累计充值与 user_quota_log 永久缺失。
            // 此处不得再次调用 one-api topup；grantQuota 自身幂等（同订单同类型只写一次），
            // 若补账失败则抛出，不标记 delivered，交由上层重试。
            userQuotaService.grantQuota(userId, orderNo, order.getQuotaPoints());

            payOrderDao.update(null, new UpdateWrapper<PayOrderEntity>()
                    .eq("id", order.getId())
                    .set("status", PayConstants.STATUS_DELIVERED)
                    .set("delivered_at", order.getDeliveredAt() == null ? new Date() : order.getDeliveredAt())
                    .set("oneapi_recharge_status", PayConstants.ONEAPI_RECHARGE_SUCCESS));
            return ConvertUtils.sourceToTarget(payOrderDao.selectById(order.getId()), PayOrderVO.class);
        }

        // 幂等3：已 paid（recharge pending/failed/未执行）不自动重试 topup，等待人工处理
        boolean resumeHardware = PayConstants.STATUS_PAID.equals(order.getStatus())
                && hardwareRecharge != null && hardwareRecharge.hasWallet(userId);
        if (PayConstants.STATUS_PAID.equals(order.getStatus()) && !resumeHardware) {
            return ConvertUtils.sourceToTarget(order, PayOrderVO.class);
        }

        if (!resumeHardware && !PayConstants.STATUS_PENDING.equals(order.getStatus())) {
            throw new RenException("订单状态不允许支付：" + order.getStatus());
        }

        // 1. pending -> paid（乐观更新；立即提交，后续充值失败订单也保留 paid）
        int updated = resumeHardware ? 1 : payOrderDao.update(null, new UpdateWrapper<PayOrderEntity>()
                .eq("id", order.getId())
                .eq("status", PayConstants.STATUS_PENDING)
                .set("status", PayConstants.STATUS_PAID)
                .set("trade_no", tradeNo)
                .set("paid_at", new Date())
                .set("oneapi_recharge_status", PayConstants.ONEAPI_RECHARGE_PENDING));
        if (updated == 0) {
            // 并发下已被其他请求处理，直接返回最新状态
            return ConvertUtils.sourceToTarget(payOrderDao.selectById(order.getId()), PayOrderVO.class);
        }

        // 2. 确保 one-api 计费账户已开通（老用户补偿兜底；失败则订单保持 paid，fail-closed）
        oneApiProvisioningService.ensureProvisioned(userId);

        // 2.5 查询 one-api 用户绑定
        SysUserOneapiBindingEntity binding = bindingDao.selectOne(
                new QueryWrapper<SysUserOneapiBindingEntity>().eq("sys_user_id", userId));
        if (binding == null) {
            // 订单保持 paid，不 delivered
            throw new RenException(PayConstants.MSG_ONEAPI_BINDING_NOT_FOUND);
        }

        if(hardwareRecharge != null) hardwareRecharge.ensureWallet(userId,binding);

        // 3. 额度换算：1 点 = 500 one-api quota
        long oneapiQuota = Math.multiplyExact(order.getQuotaPoints(), PayConstants.ONEAPI_QUOTA_PER_POINT);

        // 4. 调用 one-api /api/topup（不自动重试）
        try {
            if(hardwareRecharge != null && hardwareRecharge.hasWallet(userId)) {
                hardwareRecharge.apply(order,binding);
            } else {
            oneApiClient.topup(binding.getOneapiUserId(), oneapiQuota,
                    PayConstants.ONEAPI_RECHARGE_REMARK_PREFIX + orderNo);
            }
        } catch (RuntimeException e) {
            // topup 失败：订单保持 paid，记录失败原因，不 delivered
            payOrderDao.update(null, new UpdateWrapper<PayOrderEntity>()
                    .eq("id", order.getId())
                    .set("oneapi_recharge_status", PayConstants.ONEAPI_RECHARGE_FAILED)
                    .set("oneapi_recharge_msg", "充值发放待重试"));
            log.warn("订单 {} 充值失败，保持 paid，异常类型：{}", orderNo, e.getClass().getSimpleName());
            throw e;
        }

        // 5. 写充值流水（唯一约束 order_no，作为幂等证据）
        OneapiRechargeLogEntity rechargeLog = new OneapiRechargeLogEntity();
        rechargeLog.setOrderNo(orderNo);
        rechargeLog.setSysUserId(userId);
        rechargeLog.setOneapiUserId(binding.getOneapiUserId());
        rechargeLog.setPoints(order.getQuotaPoints());
        rechargeLog.setOneapiQuota(oneapiQuota);
        rechargeLog.setStatus(PayConstants.RECHARGE_LOG_SUCCESS);
        rechargeLogDao.insert(rechargeLog);

        // 6. 同步写 user_quota（仅展示缓存，不作为最终扣费源；最终消费以 one-api logs 为准）
        userQuotaService.grantQuota(userId, orderNo, order.getQuotaPoints());

        // 7. paid -> delivered，并写入 one-api 充值结果
        payOrderDao.update(null, new UpdateWrapper<PayOrderEntity>()
                .eq("id", order.getId())
                .set("status", PayConstants.STATUS_DELIVERED)
                .set("delivered_at", new Date())
                .set("oneapi_user_id", binding.getOneapiUserId())
                .set("oneapi_recharge_status", PayConstants.ONEAPI_RECHARGE_SUCCESS)
                .set("oneapi_recharge_at", new Date())
                .set("oneapi_recharge_quota", oneapiQuota));

        return ConvertUtils.sourceToTarget(payOrderDao.selectById(order.getId()), PayOrderVO.class);
    }

    private static String abbreviate(String s) {
        if (s == null) {
            return "充值失败";
        }
        return s.length() > 500 ? s.substring(0, 500) : s;
    }
}
