package xiaozhi.modules.device.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@TableName("ai_device_assets")
@Schema(description = "设备资源（表情包/壁纸）")
public class AiDeviceAssetsEntity {

    @TableId(type = IdType.AUTO)
    @Schema(description = "id")
    private Long id;

    @Schema(description = "设备ID")
    private String deviceId;

    @Schema(description = "文件访问路径")
    private String fileUrl;

    @Schema(description = "类型：emoji-表情包 / wallpaper-壁纸")
    private String fileType;

    @Schema(description = "资源版本号")
    private Integer version;

    @TableField(fill = FieldFill.INSERT)
    @Schema(description = "创建者")
    private Long creator;

    @TableField(fill = FieldFill.INSERT)
    @Schema(description = "创建时间")
    private Date createDate;
}
