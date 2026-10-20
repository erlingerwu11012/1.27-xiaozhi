package xiaozhi.modules.pay.dto;

import lombok.Data;

/**
 * one_api.users 插入行（id 用于回填自增主键）。
 */
@Data
public class OneApiUserRow {

    /** 自增主键（插入后回填） */
    private Long id;

    /** one-api 用户名（唯一） */
    private String username;

    /** bcrypt 密码哈希 */
    private String password;

    /** 展示名（主系统用户名快照） */
    private String displayName;

    /** 初始 quota（注册送体验额度，默认 0） */
    private long quota;
}
