package xiaozhi.modules.habit.service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import lombok.RequiredArgsConstructor;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.habit.dto.HabitDTO;
import xiaozhi.modules.useridentity.service.AccountIdentityStateService;

/** Authenticated management operations, without a fabricated speaker identity. */
@Service
@RequiredArgsConstructor
public class HabitSyncService {
    private final JdbcTemplate jdbc;
    private final AccountIdentityStateService identities;
    public Map<String,Object> options(Long account) {
        Map<String,Object> out=new LinkedHashMap<>();
        out.put("devices",jdbc.queryForList("SELECT mac_address AS deviceId,alias,device_name AS deviceName FROM ai_device WHERE user_id=? ORDER BY create_date",account));
        out.put("people",identities.snapshot(account).get("members"));
        return out;
    }
    public String validateBinding(Long account, HabitDTO dto) {
        if(account==null || dto.getDeviceId()==null || dto.getRecipientPersonId()==null) throw new RenException("请选择设备和接收人");
        if(jdbc.queryForObject("SELECT COUNT(*) FROM ai_device WHERE user_id=? AND mac_address=?",Integer.class,account,dto.getDeviceId())!=1) throw new RenException("设备不属于当前账号");
        String recipient=dto.getRecipientPersonId();
        if("all".equals(recipient)) return "公共接收人";
        List<String> names=jdbc.queryForList("SELECT display_name FROM ai_user_identity WHERE account_id=? AND user_id=? AND status='active'",String.class,account,recipient);
        if(names.size()!=1) throw new RenException("接收人未登记在当前账号中");
        return names.get(0);
    }
    public void validateContent(HabitDTO dto) {
        if(dto.getDescription().trim().getBytes(StandardCharsets.UTF_8).length>96 || dto.getIntent()!=null && dto.getIntent().getBytes(StandardCharsets.UTF_8).length>64) throw new RenException("描述最多96字节，意图最多64字节");
    }
    @Transactional
    public void update(Long account,Integer id,HabitDTO dto) {
        String name=validateBinding(account,dto);validateContent(dto);
        List<Map<String,Object>> rows=jdbc.queryForList("SELECT * FROM sys_habits WHERE id=? FOR UPDATE",id);
        if(rows.size()!=1 || !account.toString().equals(String.valueOf(rows.get(0).get("user_id")))) throw new RenException("无权修改该习惯");
        Map<String,Object> old=rows.get(0);
        boolean neverVerifiedLegacy="needs_binding".equals(old.get("sync_state")) && old.get("device_rule_id")==null;
        if(old.get("device_id")!=null && !String.valueOf(old.get("device_id")).isBlank() && !Objects.equals(old.get("device_id"),dto.getDeviceId()) && !neverVerifiedLegacy) throw new RenException("不能直接迁移设备，请先删除并等待原设备停止提醒，再在新设备创建");
        jdbc.update("UPDATE sys_habits SET description=?,intent=?,hour=?,minute=?,advance_minutes=?,device_id=?,recipient_person_id=?,recipient_display_name=?,sync_state='pending',sync_error=NULL,synced=0,config_version=config_version+1 WHERE id=?",
            dto.getDescription().trim(),dto.getIntent()==null||dto.getIntent().isBlank()?old.get("intent"):dto.getIntent(),dto.getHour(),dto.getMinute()==null?0:dto.getMinute(),dto.getAdvanceMinutes()==null?2:dto.getAdvanceMinutes(),dto.getDeviceId(),dto.getRecipientPersonId(),name,id);
    }
    private Map<String,Object> payload(Map<String,Object> r) {
        Map<String,Object> p=new LinkedHashMap<>();
        p.put("account_id",String.valueOf(r.get("user_id")));p.put("sync_id",String.valueOf(r.get("id")));
        p.put("recipient_person_id",r.get("recipient_person_id"));p.put("recipient_display_name",r.get("recipient_display_name"));
        p.put("intent",r.get("intent"));p.put("description",r.get("description"));
        p.put("hour",r.get("hour"));p.put("minute",r.get("minute"));p.put("advance_minutes",r.get("advance_minutes"));p.put("repeat_days",127);
        p.put("enabled",Boolean.TRUE.equals(r.get("enabled")) || r.get("enabled") instanceof Number n && n.intValue()==1);
        p.put("content_hash",hash(p));return p;
    }
    private String hash(Map<String,Object> p) {
        try {
            StringBuilder text=new StringBuilder();
            for(String key:List.of("account_id","sync_id","recipient_person_id","recipient_display_name","intent","description","hour","minute","advance_minutes","repeat_days","enabled")) {
                String value=key.equals("enabled")?(Boolean.TRUE.equals(p.get(key))?"1":"0"):String.valueOf(p.get(key));
                text.append(value.getBytes(StandardCharsets.UTF_8).length).append(':').append(value);
            }
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.toString().getBytes(StandardCharsets.UTF_8)));
        }catch(Exception e){throw new IllegalStateException("hash unavailable",e);}
    }
    private String bindingError(Map<String,Object> r) {
        Object account=r.get("user_id"), device=r.get("device_id"), person=r.get("recipient_person_id");
        if(account==null||device==null||person==null||String.valueOf(device).isBlank()||String.valueOf(person).isBlank()||r.get("recipient_display_name")==null) return "needs_binding";
        if(jdbc.queryForObject("SELECT COUNT(*) FROM ai_device WHERE user_id=? AND mac_address=?",Integer.class,account,device)!=1) return "ownership_mismatch";
        if(!"all".equals(person) && jdbc.queryForObject("SELECT COUNT(*) FROM ai_user_identity WHERE account_id=? AND user_id=? AND status='active'",Integer.class,account,person)!=1) return "recipient_missing";
        return null;
    }
    @Transactional
    public Map<String,Object> record(Integer id) {
        List<Map<String,Object>> rows=jdbc.queryForList("SELECT * FROM sys_habits WHERE id=? FOR UPDATE",id);
        if(rows.size()!=1) return Map.of("ok",false,"error","not_found");
        Map<String,Object> r=rows.get(0);String error=bindingError(r);
        if(error!=null){jdbc.update("UPDATE sys_habits SET synced=0,sync_state='needs_binding',sync_error=? WHERE id=?",error,id);return Map.of("ok",false,"error",error);}
        Map<String,Object> out=new LinkedHashMap<>();out.put("ok",true);out.put("device_id",r.get("device_id"));
        out.put("payload",payload(r));out.put("config_version",r.get("config_version"));return out;
    }
    public record Ack(Integer habitId,String contentHash,Long configVersion,String state,String error,Integer deviceRuleId) {}
    @Transactional
    public boolean acknowledge(Ack ack) {
        if(ack.habitId()==null||ack.configVersion()==null||ack.state()==null||!Set.of("synced","failed","upgrade_required","pending").contains(ack.state())||ack.error()!=null&&!ack.error().matches("[a-z_]{1,64}")) throw new RenException("回执无效");
        List<Map<String,Object>> rows=jdbc.queryForList("SELECT * FROM sys_habits WHERE id=? FOR UPDATE",ack.habitId());
        if(rows.size()!=1)return false;Map<String,Object> r=rows.get(0);
        if(bindingError(r)!=null || ((Number)r.get("config_version")).longValue()!=ack.configVersion() || !Objects.equals(payload(r).get("content_hash"),ack.contentHash())) return false;
        boolean saved="synced".equals(ack.state());
        if(saved && (ack.deviceRuleId()==null || ack.deviceRuleId()<(Boolean.TRUE.equals(payload(r).get("enabled"))?1:0))) throw new RenException("缺少设备保存结果");
        jdbc.update("UPDATE sys_habits SET synced=?,sync_state=?,sync_error=?,content_hash=?,device_rule_id=?,synced_at=? WHERE id=?",
            saved?1:0,ack.state(),ack.error(),ack.contentHash(),saved?ack.deviceRuleId():r.get("device_rule_id"),saved?new Date():null,ack.habitId());return true;
    }
}
