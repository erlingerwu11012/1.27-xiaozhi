package xiaozhi.modules.personmemory;

import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.*;
import lombok.Data;

@Data
public class PersonTurnDTO {
    @NotNull @Positive @JsonProperty("account_id") private Long accountId;
    @NotBlank @Pattern(regexp="[A-Za-z0-9_-]{1,64}") @JsonProperty("person_id") private String personId;
    @Min(0) private long generation;
    @Min(1) @JsonProperty("directory_version") private long directoryVersion;
    @NotBlank @Size(max=64) @JsonProperty("turn_id") private String turnId;
    @NotBlank @Size(max=64) @JsonProperty("device_id") private String deviceId;
    @NotBlank @Size(max=64) @JsonProperty("agent_id") private String agentId;
    @JsonProperty("voiceprint_id") private String voiceprintId;
    @JsonProperty("template_version") private long templateVersion;
    @JsonProperty("listen_epoch") private long listenEpoch;
    private String status;
    private String mode;
    @JsonProperty("captured_at") private Long capturedAt;
    @JsonProperty("display_name") private String displayName;
}
