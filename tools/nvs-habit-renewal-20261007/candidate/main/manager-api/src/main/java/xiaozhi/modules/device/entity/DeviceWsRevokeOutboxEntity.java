package xiaozhi.modules.device.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import lombok.Data;

@Data
@TableName("ai_device_ws_revoke_outbox")
public class DeviceWsRevokeOutboxEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String deviceId;

    private Long credentialVersion;

    private String status;

    private Integer attempts;

    private Date nextAttemptAt;

    private String lastError;

    private Date createdAt;

    private Date deliveredAt;
}
