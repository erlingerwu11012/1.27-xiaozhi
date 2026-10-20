package xiaozhi.modules.device.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import lombok.Data;

/**
 * 设备 WSS 鉴权状态（credential_version + status）。
 * device_id 为规范化 12 位 hex。
 */
@Data
@TableName("ai_device_ws_auth")
public class DeviceWsAuthEntity {

    public static final String STATUS_ACTIVE = "active";
    public static final String STATUS_UNBOUND = "unbound";
    public static final String STATUS_DISABLED = "disabled";

    @TableId(type = IdType.AUTO)
    private Long id;

    private String deviceId;

    private Long credentialVersion;

    private String status;

    /** HMAC-SHA256 hex of device bootstrap key; never store plaintext. */
    private String bootstrapKeyHash;

    /**
     * v1 tokens with iat &lt;= this Unix second are rejected forever.
     * Set on unbind/disable; never cleared on rebind.
     */
    private Long legacyRevokedBeforeIat;

    private Date updatedAt;

    private Date createdAt;
}
