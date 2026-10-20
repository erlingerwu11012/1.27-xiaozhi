package xiaozhi.modules.officialtts.entity;

import java.math.BigDecimal;
import java.util.Date;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

@Data
@TableName("official_tts_price")
public class OfficialTtsPriceEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String priceKind;
    private String operation;
    private String version;
    private String unit;
    private BigDecimal amount;
    private String status;
    private Date createdAt;
    @TableField(exist = false)
    private String lifecycleStatus;
}
