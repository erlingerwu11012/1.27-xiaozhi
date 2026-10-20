package xiaozhi.modules.pay.vo;

import java.math.BigDecimal;
import java.util.List;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

/**
 * 用户额度 VO
 */
@Data
@Schema(description = "用户额度")
public class UserQuotaVO {

    @Schema(description = "用户ID")
    private Long userId;

    @Schema(description = "当前余额（点，保留 3 位小数；优先取 one-api 实时快照）")
    private BigDecimal balance;

    @Schema(description = "累计充值额度（点）")
    private Long totalRecharge;

    @Schema(description = "累计消费额度（点，保留 3 位小数；不可用时为 null）")
    private BigDecimal totalConsume;

    @Schema(description = "余额来源：oneapi（实时快照）/ cache（缓存降级）/ none")
    private String balanceSource;

    @Schema(description = "余额是否为 one-api 实时快照")
    private Boolean balanceRealtime;

    @Schema(description = "最近额度流水")
    private List<UserQuotaLogVO> recentLogs;
}
