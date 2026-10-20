package xiaozhi.modules.officialtts.entity;

import java.util.Date;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("official_tts_job")
public class OfficialTtsJobEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long userId;
    private String agentId;
    private String jobType;
    private String status;
    private String voiceCode;
    private String requestJson;
    private String resultPath;
    private String captionText;
    private String synthesisText;
    private String usageJson;
    private String officialCostVersion;
    private String salePriceVersion;
    private Long reservedQuota;
    private Long settledQuota;
    private String billId;
    private String idempotencyKey;
    private String errorMsg;
    private Date expireAt;
    private Date createdAt;
    private Date updatedAt;
}
