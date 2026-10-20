package xiaozhi.modules.officialtts.entity;

import java.util.Date;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("official_tts_voice")
public class OfficialTtsVoiceEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long userId;
    private String agentId;
    private String kind;
    private String name;
    private String upstreamVoiceId;
    private String targetModel;
    private String channel;
    private String region;
    private String status;
    private String languageHints;
    private String previewUrl;
    private Date expireAt;
    private String billId;
    private String idempotencyKey;
    private String errorMsg;
    private Date createdAt;
    private Date updatedAt;

    /** 是否已有可试听的预览音频（非表字段） */
    @TableField(exist = false)
    private Boolean hasPreview;
}
