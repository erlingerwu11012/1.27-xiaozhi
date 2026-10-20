package xiaozhi.modules.device.vo;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "设备解绑结果（含 revoke 同步状态）")
public class DeviceUnbindResultVO {

    @Schema(description = "auth 状态是否已持久化为 unbound")
    private boolean authStatePersisted;

    @Schema(description = "sync_closed | pending | failed | noop")
    private String revokeStatus;

    @Schema(description = "同步通知是否已获 Python ack（仅 sync_closed 时为 true）")
    private boolean syncClosed;

    @Schema(description = "新的 credential_version；noop 时可能为 null")
    private Long credentialVersion;
}
