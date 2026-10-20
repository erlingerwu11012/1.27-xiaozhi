package xiaozhi.modules.agent.vo;

import lombok.Data;

import java.util.Date;

/**
 * 展示智能体声纹列表VO
 */
@Data
public class AgentVoicePrintVO {

    /**
     * 主键id
     */
    private String id;
    /**
     * 音频文件id
     */
    private String audioId;
    /**
     * 声纹来源的人姓名
     */
    private String sourceName;
    /**
     * 描述声纹来源的人
     */
    private String introduce;
    /** 统一用户ID；空值表示未绑定的历史声纹。 */
    private String userId;
    private String vectorId;
    private Long templateVersion;
    private String bindingState;
    /** 声纹所属账号，仅用于服务端构造结构化身份配置。 */
    private Long creator;
    /**
     * 创建时间
     */
    private Date createDate;
}
