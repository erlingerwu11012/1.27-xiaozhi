package xiaozhi.modules.wallpaperpack.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = false)
@TableName("ai_wallpaper_pack_audit")
public class WallpaperPackAuditEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String action;
    private Long actorUserId;
    private String deviceId;
    private String packId;
    private String taskId;
    private String detail;
    private String errorCode;
    private Date createdAt;
}
