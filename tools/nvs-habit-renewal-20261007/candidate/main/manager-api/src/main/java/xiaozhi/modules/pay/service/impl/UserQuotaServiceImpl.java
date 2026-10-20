package xiaozhi.modules.pay.service.impl;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.service.impl.BaseServiceImpl;
import xiaozhi.common.utils.ConvertUtils;
import xiaozhi.modules.pay.constant.PayConstants;
import xiaozhi.modules.pay.dao.OneApiProvisioningDao;
import xiaozhi.modules.pay.dao.SysUserOneapiBindingDao;
import xiaozhi.modules.pay.dao.UserQuotaDao;
import xiaozhi.modules.pay.dao.UserQuotaLogDao;
import xiaozhi.modules.pay.dto.BillingDailyRechargeRow;
import xiaozhi.modules.pay.dto.OneApiDailyUsageRow;
import xiaozhi.modules.pay.dto.OneApiUserSnapshotRow;
import xiaozhi.modules.pay.entity.SysUserOneapiBindingEntity;
import xiaozhi.modules.pay.entity.UserQuotaEntity;
import xiaozhi.modules.pay.entity.UserQuotaLogEntity;
import xiaozhi.modules.pay.service.UserQuotaService;
import xiaozhi.modules.pay.vo.BillingDailyVO;
import xiaozhi.modules.pay.vo.BillingSummaryVO;
import xiaozhi.modules.pay.vo.UserQuotaLogVO;
import xiaozhi.modules.pay.vo.UserQuotaVO;

@Slf4j
@Service
@RequiredArgsConstructor
public class UserQuotaServiceImpl extends BaseServiceImpl<UserQuotaDao, UserQuotaEntity>
        implements UserQuotaService {

    /** one-api 原始 quota 与「点」的换算基数（1 点 = 500 quota） */
    private static final BigDecimal QUOTA_PER_POINT = BigDecimal.valueOf(PayConstants.ONEAPI_QUOTA_PER_POINT);

    private final UserQuotaLogDao userQuotaLogDao;
    private final SysUserOneapiBindingDao bindingDao;
    private final OneApiProvisioningDao oneApiProvisioningDao;
    @org.springframework.beans.factory.annotation.Autowired
    private xiaozhi.modules.pay.service.HardwareBillingReadService hardwareLedger;

    @Override
    public UserQuotaVO getMyQuota(Long userId) {
        UserQuotaEntity cache = baseDao.selectOne(new QueryWrapper<UserQuotaEntity>().eq("user_id", userId));
        BalanceResolution balance = resolveBalance(userId, cache);

        UserQuotaVO vo = new UserQuotaVO();
        vo.setUserId(userId);
        vo.setBalance(balance.balance);
        vo.setTotalRecharge(cache == null || cache.getTotalRecharge() == null ? 0L : cache.getTotalRecharge());
        vo.setTotalConsume(balance.totalConsume);
        vo.setBalanceSource(balance.source);
        vo.setBalanceRealtime(balance.realtime);

        // 最近流水
        List<UserQuotaLogEntity> logs = userQuotaLogDao.selectList(new QueryWrapper<UserQuotaLogEntity>()
                .eq("user_id", userId)
                .orderByDesc("id")
                .last("LIMIT 20"));
        vo.setRecentLogs(ConvertUtils.sourceToTarget(logs, UserQuotaLogVO.class));
        return vo;
    }

    @Override
    public BillingSummaryVO getBillingSummary(Long userId, int days) {
        int rangeDays = days <= 0 ? 7 : Math.min(days, 90);
        ZoneId zone = ZoneId.of(PayConstants.BILLING_ZONE_ID);
        LocalDate today = LocalDate.now(zone);
        LocalDate startDate = today.minusDays(rangeDays - 1L);

        UserQuotaEntity cache = baseDao.selectOne(new QueryWrapper<UserQuotaEntity>().eq("user_id", userId));
        BalanceResolution balance = resolveBalance(userId, cache);

        // ---- 消费用量：直接聚合 one-api 账本（不落本地消费流水） ----
        boolean consumptionAvailable = false;
        String unavailableReason = null;
        Map<LocalDate, BigDecimal> usageByDay = new HashMap<>();
        Long oneapiUserId = balance.oneapiUserId;
        if (oneapiUserId == null) {
            unavailableReason = PayConstants.CONSUME_REASON_NO_BINDING;
        } else if ("hardware_ledger".equals(balance.source)) {
            try {
                usageByDay.putAll(hardwareLedger.dailyUsage(userId,startDate.atStartOfDay(zone).toEpochSecond(),today.plusDays(1).atStartOfDay(zone).toEpochSecond()));
                consumptionAvailable=true;
            } catch(Exception e) {unavailableReason=PayConstants.CONSUME_REASON_LOGS_UNREADABLE;}
        } else if (isConsumeLogDisabled()) {
            unavailableReason = PayConstants.CONSUME_REASON_LOGS_DISABLED;
        } else {
            long startEpoch = startDate.atStartOfDay(zone).toEpochSecond();
            long endEpoch = today.plusDays(1).atStartOfDay(zone).toEpochSecond();
            try {
                List<OneApiDailyUsageRow> rows = oneApiProvisioningDao
                        .sumDailyConsumeByUser(oneapiUserId, startEpoch, endEpoch);
                for (OneApiDailyUsageRow row : rows) {
                    if (row == null || row.getDayIndex() == null) {
                        continue;
                    }
                    LocalDate day = LocalDate.ofEpochDay(row.getDayIndex());
                    // 先按日求和原始 quota，再统一换算为点数，避免逐条整除后累加的精度损失
                    usageByDay.merge(day, quotaToPoints(row.getQuota()), BigDecimal::add);
                }
                consumptionAvailable = true;
            } catch (Exception e) {
                unavailableReason = PayConstants.CONSUME_REASON_LOGS_UNREADABLE;
                log.warn("读取 one-api 消费日志失败，用量明细不可用 userId={} oneapiUserId={}",
                        userId, oneapiUserId, e);
            }
        }

        // ---- 充值汇总：本地 user_quota_log 按日分组，金额关联成功发货订单 ----
        Date start = Date.from(startDate.atStartOfDay(zone).toInstant());
        Date end = Date.from(today.plusDays(1).atStartOfDay(zone).toInstant());
        List<BillingDailyRechargeRow> rechargeRows = userQuotaLogDao.sumDailyRecharge(userId, start, end);
        Map<LocalDate, BillingDailyRechargeRow> rechargeByDay = new HashMap<>();
        for (BillingDailyRechargeRow row : rechargeRows) {
            if (row == null || row.getDay() == null) {
                continue;
            }
            try {
                rechargeByDay.put(LocalDate.parse(row.getDay()), row);
            } catch (Exception ignore) {
                log.warn("忽略无法解析的充值汇总日期：{}", row.getDay());
            }
        }

        // ---- 补齐区间内每一天（含无充值/无消费日期） ----
        List<BillingDailyVO> daily = new ArrayList<>();
        for (LocalDate day = startDate; !day.isAfter(today); day = day.plusDays(1)) {
            BillingDailyVO vo = new BillingDailyVO();
            vo.setDate(day.toString());

            BillingDailyRechargeRow recharge = rechargeByDay.get(day);
            BigDecimal rechargePoints = recharge == null || recharge.getPoints() == null
                    ? BigDecimal.ZERO.setScale(PayConstants.POINTS_SCALE)
                    : BigDecimal.valueOf(recharge.getPoints()).setScale(PayConstants.POINTS_SCALE);
            vo.setRechargePoints(rechargePoints);
            vo.setRechargeAmountCents(recharge == null || recharge.getAmountCents() == null ? 0L
                    : recharge.getAmountCents());
            vo.setRechargeCount(recharge == null || recharge.getRechargeCount() == null ? 0
                    : recharge.getRechargeCount().intValue());

            if (consumptionAvailable) {
                BigDecimal usage = usageByDay.getOrDefault(day,
                        BigDecimal.ZERO.setScale(PayConstants.POINTS_SCALE));
                vo.setUsagePoints(usage);
                vo.setNetChangePoints(rechargePoints.subtract(usage));
            } else {
                // 日志不可用：明确留空，绝不伪装成 0 用量
                vo.setUsagePoints(null);
                vo.setNetChangePoints(null);
            }
            daily.add(vo);
        }

        BillingSummaryVO summary = new BillingSummaryVO();
        summary.setDays(rangeDays);
        summary.setStartDate(startDate.toString());
        summary.setEndDate(today.toString());
        summary.setBalancePoints(balance.balance);
        summary.setBalanceSource(balance.source);
        summary.setBalanceRealtime(balance.realtime);
        summary.setTotalConsumePoints(balance.totalConsume);
        summary.setConsumptionAvailable(consumptionAvailable);
        summary.setConsumptionUnavailableReason(unavailableReason);
        summary.setDaily(daily);
        return summary;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void grantQuota(Long userId, String orderNo, long points) {
        // 幂等保护：同一订单同一变更类型只允许写入一次
        Long count = userQuotaLogDao.selectCount(new QueryWrapper<UserQuotaLogEntity>()
                .eq("order_no", orderNo)
                .eq("change_type", PayConstants.CHANGE_TYPE_RECHARGE));
        if (count != null && count > 0) {
            log.warn("订单 {} 已发放过额度，跳过重复发放", orderNo);
            return;
        }

        // 只累加累计充值并确保记录存在；余额缓存改由 one-api 实时快照覆盖，避免重复叠加
        baseDao.incrementRechargeOnly(userId, points);

        // 充值成功后以 one-api 快照刷新余额缓存（topup 已在调用前完成）
        BigDecimal balanceAfter = syncBalanceCacheFromOneApi(userId, orderNo, points);

        UserQuotaLogEntity logEntity = new UserQuotaLogEntity();
        logEntity.setUserId(userId);
        logEntity.setOrderNo(orderNo);
        logEntity.setChangeType(PayConstants.CHANGE_TYPE_RECHARGE);
        logEntity.setChangeAmount(points);
        logEntity.setBalanceAfter(pointsToCacheLong(balanceAfter));
        logEntity.setRemark("充值发放额度");
        userQuotaLogDao.insert(logEntity);
    }

    /**
     * 充值成功后读取 one-api 快照并刷新余额/累计消费缓存。
     *
     * @return 用于流水的「变更后余额（点）」；快照不可用时回退为本地缓存值，
     *         绝不因读取失败而把缓存标记为实时或重复叠加。
     */
    private BigDecimal syncBalanceCacheFromOneApi(Long userId, String orderNo, long rechargePoints) {
        SysUserOneapiBindingEntity binding = bindingDao.selectOne(
                new QueryWrapper<SysUserOneapiBindingEntity>().eq("sys_user_id", userId));
        if (binding != null && binding.getOneapiUserId() != null) {
            try {
                OneApiUserSnapshotRow snapshot = oneApiProvisioningDao
                        .selectUserSnapshot(binding.getOneapiUserId());
                if (snapshot != null) {
                    BigDecimal balance = quotaToPoints(snapshot.getQuota());
                    BigDecimal used = quotaToPoints(snapshot.getUsedQuota());
                    baseDao.updateSnapshotCache(userId, pointsToCacheLong(balance), pointsToCacheLong(used));
                    return balance;
                }
            } catch (Exception e) {
                log.warn("充值后读取 one-api 快照失败，保留本地余额缓存并据实记流水 userId={} orderNo={}",
                        userId, orderNo, e);
            }
        }
        UserQuotaEntity cache = baseDao.selectOne(new QueryWrapper<UserQuotaEntity>().eq("user_id", userId));
        if (cache != null && cache.getBalance() != null) {
            return BigDecimal.valueOf(cache.getBalance());
        }
        return BigDecimal.valueOf(rechargePoints);
    }

    /**
     * 解析当前用户余额：优先 one-api 实时快照，读取失败时降级为带来源标记的本地缓存。
     */
    private BalanceResolution resolveBalance(Long userId, UserQuotaEntity cache) {
        BalanceResolution resolution = new BalanceResolution();
        SysUserOneapiBindingEntity binding = bindingDao.selectOne(
                new QueryWrapper<SysUserOneapiBindingEntity>().eq("sys_user_id", userId));
        Long oneapiUserId = binding == null ? null : binding.getOneapiUserId();
        resolution.oneapiUserId = oneapiUserId;

        if (oneapiUserId != null && hardwareLedger != null) {
            Map<String,BigDecimal> exact=hardwareLedger.walletBalance(userId);
            if(exact!=null) {
                resolution.balance=exact.get("balance");resolution.totalConsume=exact.get("totalConsume");
                resolution.source="hardware_ledger";resolution.realtime=true;return resolution;
            }
        }
        if (oneapiUserId != null) {
            try {
                OneApiUserSnapshotRow snapshot = oneApiProvisioningDao.selectUserSnapshot(oneapiUserId);
                if (snapshot != null) {
                    resolution.balance = quotaToPoints(snapshot.getQuota());
                    resolution.totalConsume = quotaToPoints(snapshot.getUsedQuota());
                    resolution.source = PayConstants.BALANCE_SOURCE_ONEAPI;
                    resolution.realtime = true;
                    // 同步缓存（展示用途）；失败不影响实时值返回
                    try {
                        baseDao.updateSnapshotCache(userId, pointsToCacheLong(resolution.balance),
                                pointsToCacheLong(resolution.totalConsume));
                    } catch (Exception e) {
                        log.warn("同步 user_quota 缓存失败 userId={}", userId, e);
                    }
                    return resolution;
                }
                log.warn("one-api 用户 {} 无快照记录，降级使用本地缓存 userId={}", oneapiUserId, userId);
            } catch (Exception e) {
                log.warn("读取 one-api 余额快照失败，降级使用本地缓存 userId={} oneapiUserId={}",
                        userId, oneapiUserId, e);
            }
        }

        // 降级：返回带来源标记的缓存值（不冒充实时余额）
        resolution.balance = cache == null || cache.getBalance() == null
                ? BigDecimal.ZERO.setScale(PayConstants.POINTS_SCALE)
                : BigDecimal.valueOf(cache.getBalance()).setScale(PayConstants.POINTS_SCALE);
        resolution.totalConsume = cache == null || cache.getTotalConsume() == null
                ? BigDecimal.ZERO.setScale(PayConstants.POINTS_SCALE)
                : BigDecimal.valueOf(cache.getTotalConsume()).setScale(PayConstants.POINTS_SCALE);
        resolution.source = cache == null ? PayConstants.BALANCE_SOURCE_NONE : PayConstants.BALANCE_SOURCE_CACHE;
        resolution.realtime = false;
        return resolution;
    }

    /**
     * 核查 one-api 运行时是否关闭了消费日志记录。
     *
     * <p>options 表未显式配置时按 one-api 默认（开启）处理；读取异常同样按默认开启处理，
     * 若日志库同时不可读会在实际聚合时被标记为不可用。</p>
     */
    private boolean isConsumeLogDisabled() {
        try {
            String value = oneApiProvisioningDao.findLogConsumeEnabled();
            return value != null && "false".equalsIgnoreCase(value.trim());
        } catch (Exception e) {
            log.warn("读取 one-api LogConsumeEnabled 失败，按默认开启处理：{}", e.getMessage());
            return false;
        }
    }

    /** 原始 quota 换算为点数，保留 3 位小数（先求和后统一换算，避免逐条整除误差）。 */
    private BigDecimal quotaToPoints(Long quota) {
        if (quota == null) {
            return BigDecimal.ZERO.setScale(PayConstants.POINTS_SCALE);
        }
        return new BigDecimal(quota).divide(QUOTA_PER_POINT, PayConstants.POINTS_SCALE, RoundingMode.HALF_UP);
    }

    /** 点数按四舍五入落到整数缓存列。 */
    private long pointsToCacheLong(BigDecimal points) {
        return points.setScale(0, RoundingMode.HALF_UP).longValue();
    }

    /** 余额解析结果（含 user_quota 缓存与 one-api 绑定信息）。 */
    private static class BalanceResolution {
        private BigDecimal balance;
        private BigDecimal totalConsume;
        private String source;
        private boolean realtime;
        private Long oneapiUserId;
    }
}
