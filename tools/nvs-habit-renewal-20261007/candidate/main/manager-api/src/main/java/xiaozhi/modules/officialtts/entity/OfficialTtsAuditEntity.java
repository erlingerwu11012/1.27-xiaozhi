package xiaozhi.modules.officialtts.entity;

import java.util.Date;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("official_tts_audit")
public class OfficialTtsAuditEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long userId;
    private Long actorId;
    private String action;
    private String objectType;
    private String objectId;
    private String detail;
    @com.baomidou.mybatisplus.annotation.TableField("operation_id")
    private String operationId;
    private Date createdAt;
}
