package xiaozhi.modules.pay.dto;

import lombok.Data;

/**
 * one_api.users 余额快照行。
 *
 * <p>quota / usedQuota 均为 one-api 原始 quota 单位（1 点 = 500 quota），
 * 只做只读，不参与扣费逻辑。</p>
 */
@Data
public class OneApiUserSnapshotRow {

    /** one_api.users.id */
    private Long id;

    /** 当前剩余额度（原始 quota 单位） */
    private Long quota;

    /** 累计已用额度（原始 quota 单位） */
    private Long usedQuota;
}
