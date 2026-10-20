package xiaozhi.modules.useridentity.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class UserIdentityDisplayNameDTO {
    @NotBlank(message = "显示名不能为空")
    @Size(max = 64, message = "显示名不能超过64个字符")
    private String displayName;
}
