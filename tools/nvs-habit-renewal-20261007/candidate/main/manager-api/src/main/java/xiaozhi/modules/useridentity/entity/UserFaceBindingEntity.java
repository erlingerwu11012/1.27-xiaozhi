package xiaozhi.modules.useridentity.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import lombok.Data;

/** face-api profile 到统一用户的显式绑定，profile 本身仍保留 usr_* 标识。 */
@Data
@TableName("ai_user_face_binding")
public class UserFaceBindingEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long accountId;
    private String userId;
    private String faceProfileId;
    @TableField(fill = FieldFill.INSERT)
    private Long creator;
    @TableField(fill = FieldFill.INSERT)
    private Date createDate;
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private Long updater;
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private Date updateDate;
}
