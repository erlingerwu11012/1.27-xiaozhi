package xiaozhi.modules.pay.dto;

import lombok.Data;

/**
 * one_api.tokens 插入行（id 用于回填自增主键）。
 */
@Data
public class OneApiTokenRow {

    /** 自增主键（插入后回填） */
    private Long id;

    /** 归属 one-api 用户ID */
    private Long userId;

    /** token key（48 字符，不含 sk- 前缀，明文仅内存持有） */
    private String key;

    /** token 名称 */
    private String name;

    /** 创建/访问时间（Unix 秒） */
    private long createdTime;

    /** 允许使用的模型列表（逗号分隔） */
    private String models;
}
