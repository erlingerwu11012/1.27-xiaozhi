package xiaozhi.modules.pay.dao;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import xiaozhi.modules.pay.entity.UserQuotaEntity;

/**
 * 用户额度 DAO
 */
@Mapper
public interface UserQuotaDao extends BaseMapper<UserQuotaEntity> {

    /**
     * 充值发放额度（原子 upsert）：余额与累计充值同时增加指定点数。
     * 依赖 user_quota.user_id 唯一键，不存在则插入，存在则累加。
     */
    @Insert("INSERT INTO user_quota (user_id, balance, total_recharge, total_consume) " +
            "VALUES (#{userId}, #{points}, #{points}, 0) " +
            "ON DUPLICATE KEY UPDATE " +
            "balance = balance + VALUES(balance), " +
            "total_recharge = total_recharge + VALUES(total_recharge)")
    int upsertRecharge(@Param("userId") Long userId, @Param("points") long points);

    /**
     * 仅累加累计充值并确保记录存在（不触碰 balance）。
     *
     * <p>余额缓存以 one-api 实时快照为准，充值成功后由
     * {@link #updateSnapshotCache(Long, Long, Long)} 覆盖，因此这里不再按充值点数叠加 balance，
     * 避免重复累加。</p>
     */
    @Insert("INSERT INTO user_quota (user_id, balance, total_recharge, total_consume) " +
            "VALUES (#{userId}, 0, #{points}, 0) " +
            "ON DUPLICATE KEY UPDATE total_recharge = total_recharge + VALUES(total_recharge)")
    int incrementRechargeOnly(@Param("userId") Long userId, @Param("points") long points);

    /**
     * 以 one-api 快照覆盖本地余额缓存（balance 为点数，totalConsume 为点数）。
     *
     * <p>仅缓存展示用途，不作为扣费源；列类型为整数「点」，调用方需先按展示精度四舍五入。</p>
     */
    @Update("UPDATE user_quota SET balance = #{balance}, total_consume = #{totalConsume} " +
            "WHERE user_id = #{userId}")
    int updateSnapshotCache(@Param("userId") Long userId,
            @Param("balance") long balance,
            @Param("totalConsume") long totalConsume);
}
