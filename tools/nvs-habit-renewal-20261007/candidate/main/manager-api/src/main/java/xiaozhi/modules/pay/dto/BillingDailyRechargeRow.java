package xiaozhi.modules.pay.dto;

import lombok.Data;

/**
 * user_quota_log 按自然日聚合的充值行（change_type=recharge）。
 */
@Data
public class BillingDailyRechargeRow {

    /** 自然日（yyyy-MM-dd，按 Asia/Shanghai） */
    private String day;

    /** 当日到账点数之和 */
    private Long points;

    /** 当日成功发放笔数 */
    private Long rechargeCount;

    /** 当日成功发放订单金额之和（分） */
    private Long amountCents;
}
