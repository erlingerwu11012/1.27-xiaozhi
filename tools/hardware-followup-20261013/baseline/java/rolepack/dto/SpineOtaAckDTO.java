package xiaozhi.modules.rolepack.dto;

import com.fasterxml.jackson.annotation.JsonAlias;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
@Schema(description = "设备 spine_ota_status 回执")
public class SpineOtaAckDTO {

    @NotBlank
    @JsonAlias({ "task_id" })
    private String taskId;

    @NotBlank
    @JsonAlias({ "pack_id" })
    private String packId;

    @NotBlank
    @Schema(description = "waiting|downloading|verifying|applying|success|failed")
    private String phase;

    private Integer progress;

    private String error;
}
