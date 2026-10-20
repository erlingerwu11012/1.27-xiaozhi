package xiaozhi.modules.officialtts.entity;

import java.math.BigDecimal;
import java.util.Date;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("official_tts_ledger")
public class OfficialTtsLedgerEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long userId;
    private Long jobId;
    private String phase;
    private Long quota;
    private BigDecimal officialCost;
    private BigDecimal salePoints;
    private String note;
    private Date createdAt;
}
