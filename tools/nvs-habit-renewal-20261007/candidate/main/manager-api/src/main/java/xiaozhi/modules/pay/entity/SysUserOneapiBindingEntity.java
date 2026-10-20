package xiaozhi.modules.pay.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.EqualsAndHashCode;

/**
 * 主系统用户与 one-api 用户绑定实体
 */
@Data
@EqualsAndHashCode(callSuper = false)
@TableName("sys_user_oneapi_binding")
@Schema(description = "主系统用户与one-api用户绑定")
public class SysUserOneapiBindingEntity {

    @TableId(type = IdType.AUTO)
    @Schema(description = "主键")
    private Long id;

    @Schema(description = "主系统用户ID（sys_user.id）")
    private Long sysUserId;

    @Schema(description = "one-api 用户ID（one_api.users.id）")
    private Long oneapiUserId;

    @Schema(description = "one-api 用户名快照")
    private String oneapiUsername;

    @Schema(description = "one-api tokens.id（预留，阶段1不用）")
    private Long oneapiTokenId;

    @Schema(description = "one-api token 名称（预留）")
    private String oneapiTokenName;

    @Schema(description = "one-api token key 密文（预留，阶段1不存明文）")
    private String oneapiTokenKeyCipher;

    @Schema(description = "token key SHA-256 指纹（预留，用于轮换检测）")
    private String oneapiTokenKeyFingerprint;

    @Schema(description = "创建时间")
    private Date createdAt;

    @Schema(description = "更新时间")
    private Date updatedAt;
}
