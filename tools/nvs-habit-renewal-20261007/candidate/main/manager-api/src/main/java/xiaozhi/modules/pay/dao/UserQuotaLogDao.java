package xiaozhi.modules.pay.dao;

import java.util.Date;
import java.util.List;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import xiaozhi.modules.pay.dto.BillingDailyRechargeRow;
import xiaozhi.modules.pay.entity.UserQuotaLogEntity;

/**
 * 用户额度流水 DAO
 */
@Mapper
public interface UserQuotaLogDao extends BaseMapper<UserQuotaLogEntity> {

    /**
     * 按自然日聚合当前用户的充值流水（change_type=recharge）。
     *
     * <p>created_at 为本地 datetime（Asia/Shanghai 墙钟），因此直接按 DATE 分组即自然日；
     * 金额取关联且已成功发货（delivered）的 pay_order.amount_cents。</p>
     *
     * @param userId 用户ID
     * @param start  起始时间（含）
     * @param end    结束时间（不含）
     */
    @Select("SELECT DATE_FORMAT(l.created_at, '%Y-%m-%d') AS day, " +
            "COALESCE(SUM(l.change_amount), 0) AS points, " +
            "COUNT(*) AS recharge_count, " +
            "COALESCE(SUM(CASE WHEN o.status = 'delivered' THEN o.amount_cents ELSE 0 END), 0) AS amount_cents " +
            "FROM user_quota_log l " +
            "LEFT JOIN pay_order o ON o.out_trade_no = l.order_no " +
            "WHERE l.user_id = #{userId} AND l.change_type = 'recharge' " +
            "AND l.created_at >= #{start} AND l.created_at < #{end} " +
            "GROUP BY day ORDER BY day")
    List<BillingDailyRechargeRow> sumDailyRecharge(@Param("userId") Long userId,
            @Param("start") Date start,
            @Param("end") Date end);
}
