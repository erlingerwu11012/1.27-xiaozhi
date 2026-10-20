package xiaozhi.modules.useridentity.entity;

import java.util.Date;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import lombok.Data;

/** 账号范围内稳定的统一用户主档案。 */
@Data
@TableName("ai_user_identity")
public class UserIdentityEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long accountId;
    private String userId;
    private String displayName;
    private String status;
    private String kind;
    @TableField(exist = false)
    private String displayKey;
    @TableField(fill = FieldFill.INSERT)
    private Long creator;
    @TableField(fill = FieldFill.INSERT)
    private Date createDate;
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private Long updater;
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private Date updateDate;
}
