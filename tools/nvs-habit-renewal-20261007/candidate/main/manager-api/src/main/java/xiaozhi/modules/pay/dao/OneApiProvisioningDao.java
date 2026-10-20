package xiaozhi.modules.pay.dao;

import java.util.List;

import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import xiaozhi.modules.pay.dto.OneApiDailyUsageRow;
import xiaozhi.modules.pay.dto.OneApiTokenRow;
import xiaozhi.modules.pay.dto.OneApiUserRow;
import xiaozhi.modules.pay.dto.OneApiUserSnapshotRow;

/**
 * one-api 计费账户开通 DAO。
 *
 * 说明：one-api 无“管理员为用户创建 token”的官方 API（AddToken 的 userId 取当前登录用户），
 * 因此此处通过跨库全限定名直接插入 one_api.users / one_api.tokens（只创建记录，不 UPDATE quota）。
 * 充值仍走官方 /api/topup；扣费由 one-api 内部按 token -> user 归属自动完成。
 */
@Mapper
public interface OneApiProvisioningDao {

    @Insert("INSERT INTO one_api.users " +
            "(username, password, display_name, role, status, quota, used_quota, request_count, `group`) " +
            "VALUES (#{username}, #{password}, #{displayName}, 1, 1, #{quota}, 0, 0, 'default')")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insertUser(OneApiUserRow row);

    @Insert("INSERT INTO one_api.tokens " +
            "(user_id, `key`, status, name, created_time, accessed_time, expired_time, " +
            " remain_quota, unlimited_quota, used_quota, models, subnet) " +
            "VALUES (#{userId}, #{key}, 1, #{name}, #{createdTime}, #{createdTime}, -1, 0, 1, 0, #{models}, '')")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insertToken(OneApiTokenRow row);

    @Select("SELECT id FROM one_api.users WHERE username = #{username} LIMIT 1")
    Long findUserIdByUsername(@Param("username") String username);

    @Select("SELECT id FROM one_api.tokens WHERE user_id = #{userId} AND name = #{name} LIMIT 1")
    Long findTokenIdByUserIdAndName(@Param("userId") Long userId, @Param("name") String name);

    @Select("SELECT `key` FROM one_api.tokens WHERE id = #{id} LIMIT 1")
    String findTokenKeyById(@Param("id") Long id);

    @Update("UPDATE one_api.tokens SET models = #{models} WHERE name = #{name}")
    int updateModelsByName(@Param("name") String name, @Param("models") String models);

    @Update("UPDATE one_api.tokens SET models=CONCAT(models,',memory') WHERE id=#{id} AND user_id=#{owner} AND name='xiaozhi-device' AND models IS NOT NULL AND models<>'' AND FIND_IN_SET('memory',models)=0")
    int enableMemoryForOwnedDeviceToken(@Param("id") Long id,@Param("owner") Long owner);

    @Update("UPDATE one_api.tokens SET models=CONCAT(models,',',#{model}) WHERE id=#{id} AND user_id=#{owner} AND name='xiaozhi-device' AND models IS NOT NULL AND models<>'' AND FIND_IN_SET(#{model},models)=0")
    int enableHardwareModelForOwnedDeviceToken(@Param("id") Long id,@Param("owner") Long owner,@Param("model") String model);

    @Delete("DELETE FROM one_api.tokens WHERE id = #{id}")
    int deleteToken(@Param("id") Long id);

    @Delete("DELETE FROM one_api.users WHERE id = #{id}")
    int deleteUser(@Param("id") Long id);

    /**
     * 读取 one-api 用户余额快照（只读，不参与扣费）。
     */
    @Select("SELECT id, quota, used_quota FROM one_api.users WHERE id = #{id} LIMIT 1")
    OneApiUserSnapshotRow selectUserSnapshot(@Param("id") Long id);

    /**
     * 按自然日聚合指定 one-api 用户的消费额度（type=2）。
     *
     * <p>created_at 为 Unix 秒；加固定 UTC+8 偏移后整除 86400 得到 Asia/Shanghai 自然日序号，
     * 纯整数运算，不依赖 MySQL 会话时区，避免跨日错位。</p>
     *
     * @param userId     one_api.users.id
     * @param startEpoch 起始 epoch 秒（含）
     * @param endEpoch   结束 epoch 秒（不含）
     */
    @Select("SELECT ((created_at + 28800) DIV 86400) AS day_index, SUM(quota) AS quota " +
            "FROM one_api.logs " +
            "WHERE user_id = #{userId} AND type = 2 " +
            "AND created_at >= #{startEpoch} AND created_at < #{endEpoch} " +
            "GROUP BY day_index ORDER BY day_index")
    List<OneApiDailyUsageRow> sumDailyConsumeByUser(@Param("userId") Long userId,
            @Param("startEpoch") long startEpoch,
            @Param("endEpoch") long endEpoch);

    /**
     * 读取 one-api 运行时「消费日志记录」开关。
     *
     * <p>返回 null 表示 options 表中未显式配置（one-api 默认开启）。
     */
    @Select("SELECT `value` FROM one_api.options WHERE `key` = 'LogConsumeEnabled' LIMIT 1")
    String findLogConsumeEnabled();
}
