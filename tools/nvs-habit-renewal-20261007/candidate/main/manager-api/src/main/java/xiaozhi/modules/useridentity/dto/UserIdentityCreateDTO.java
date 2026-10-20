package xiaozhi.modules.useridentity.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class UserIdentityCreateDTO {
    /** Ignored for compatibility; only the server allocates stable IDs. */
    private String userId;

    @NotBlank(message = "显示名不能为空")
    @Size(max = 64, message = "显示名不能超过64个字符")
    private String displayName;
}
