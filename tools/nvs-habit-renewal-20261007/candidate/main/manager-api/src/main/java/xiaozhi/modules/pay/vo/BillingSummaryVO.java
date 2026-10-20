package xiaozhi.modules.pay.vo;

import java.math.BigDecimal;
import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

/**
 * 当前用户账单汇总（余额 + 每日用量/账单）。
 */
@Data
@Schema(description = "当前用户账单汇总")
public class BillingSummaryVO {

    @Schema(description = "统计天数")
    private Integer days;

    @Schema(description = "统计起始日（含，yyyy-MM-dd）")
    private String startDate;

    @Schema(description = "统计结束日（含，yyyy-MM-dd）")
    private String endDate;

    @Schema(description = "当前余额（点，保留 3 位小数）")
    private BigDecimal balancePoints;

    @Schema(description = "余额来源：oneapi（实时快照）/ cache（缓存降级）/ none")
    private String balanceSource;

    @Schema(description = "余额是否为 one-api 实时快照")
    private Boolean balanceRealtime;

    @Schema(description = "累计消费（点，保留 3 位小数；不可用时为 null）")
    private BigDecimal totalConsumePoints;

    @Schema(description = "消费日志是否可用")
    private Boolean consumptionAvailable;

    @Schema(description = "消费日志不可用原因：no_binding/logs_disabled/logs_unreadable，可用时为 null")
    private String consumptionUnavailableReason;

    @Schema(description = "按自然日汇总的每日趋势与账单")
    private List<BillingDailyVO> daily;
}
