package xiaozhi.modules.officialtts.entity;

import java.util.Date;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("official_tts_asset")
public class OfficialTtsAssetEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long userId;
    private Long voiceId;
    private String purpose;
    private String storagePath;
    private String mimeType;
    private Integer durationMs;
    private Date expireAt;
    private Date createdAt;
}
