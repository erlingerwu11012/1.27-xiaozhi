package xiaozhi.modules.rolepack.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = false)
@TableName("ai_device_visual_role")
public class DeviceVisualRoleEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String deviceId;
    private String packId;
    private String version;
    private String taskId;
    private Date updatedAt;
}
