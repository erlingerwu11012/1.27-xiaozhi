package xiaozhi.modules.pay.dto;

import lombok.Data;

/**
 * one_api.logs 按自然日聚合的消费行（type=2）。
 *
 * <p>dayIndex 为「以 UTC+8（Asia/Shanghai）为基准的自然日序号」，
 * 即 epoch 秒加固定偏移后整除 86400；调用方通过
 * {@link java.time.LocalDate#ofEpochDay(long)} 还原为日期。</p>
 */
@Data
public class OneApiDailyUsageRow {

    /** 自然日序号（Asia/Shanghai） */
    private Long dayIndex;

    /** 当日消费 quota 之和（原始 quota 单位，正数） */
    private Long quota;
}
