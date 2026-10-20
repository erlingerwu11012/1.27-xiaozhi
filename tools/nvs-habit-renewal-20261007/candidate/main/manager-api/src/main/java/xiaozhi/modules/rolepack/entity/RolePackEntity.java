package xiaozhi.modules.rolepack.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;
import lombok.EqualsAndHashCode;

@Data
@EqualsAndHashCode(callSuper = false)
@TableName("ai_role_pack")
@Schema(description = "官方视觉 Spine 角色包")
public class RolePackEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String packId;
    private String displayName;
    private String description;
    private String version;
    private String objectKey;
    private Long size;
    private String sha256;
    private String signature;
    private String signatureAlgorithm;
    private String minFw;
    /** JSON 数组字符串，如 ["esp-box-3","lichuang-dev"] */
    private String boardModelAllowlist;
    private String previewUrl;
    private String previewImageObjectKey;
    private String previewVideoObjectKey;
    private String status;
    private Long createdBy;
    private Date createdAt;
    private Date updatedAt;
}
