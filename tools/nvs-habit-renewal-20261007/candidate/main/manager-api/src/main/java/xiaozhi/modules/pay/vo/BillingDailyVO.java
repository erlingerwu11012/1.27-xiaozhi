package xiaozhi.modules.pay.vo;

import java.math.BigDecimal;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

/**
 * 按自然日汇总的账单行。
 *
 * <p>当日用量直接来自 one-api 账本聚合，不落本地消费流水；
 * 消费日志不可用时 {@code usagePoints} 与 {@code netChangePoints} 为 {@code null}，
 * 由 {@link BillingSummaryVO#getConsumptionAvailable()} 明确标记，绝不伪造为 0。</p>
 */
@Data
@Schema(description = "按日汇总账单")
public class BillingDailyVO {

    @Schema(description = "自然日（yyyy-MM-dd，Asia/Shanghai）")
    private String date;

    @Schema(description = "当日到账点数（点）")
    private BigDecimal rechargePoints;

    @Schema(description = "当日充值金额（分）")
    private Long rechargeAmountCents;

    @Schema(description = "当日成功充值笔数")
    private Integer rechargeCount;

    @Schema(description = "当日模型消费（点，保留 3 位小数；消费日志不可用时为 null）")
    private BigDecimal usagePoints;

    @Schema(description = "当日净变动（点）= 到账点数 - 当日消费；消费不可用时为 null")
    private BigDecimal netChangePoints;
}
