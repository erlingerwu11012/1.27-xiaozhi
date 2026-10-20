package xiaozhi.modules.personmemory;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Duration;
import java.util.*;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.useridentity.service.AccountIdentityStateService;

@Service
@RequiredArgsConstructor
public class PersonMemoryService {
    private final JdbcTemplate jdbc;
    private final AccountIdentityStateService identities;
    private final MemoryGatewayClient gateway;
    private final ObjectMapper json;
    @Value("${memory.product.enabled:false}") private boolean enabled;
    @Value("${memory.portrait.enabled:false}") private boolean portraits;
    @Value("${memory.portrait.schema-id:}") private String portraitSchema;
    @Value("${memory.material.max-chars:16000}") private int maxChars;
    @Value("${memory.search.top-k:5}") private int topK=5;
    @Value("${memory.search.max-fact-chars:1500}") private int factChars=1500;
    @Value("${memory.search.timeout-millis:850}") private int searchTimeout=850;

    public boolean enabled(){return enabled;}
    public boolean portraitsEnabled(){return enabled && portraits && !portraitSchema.isBlank();}

    public void validateActor(PersonTurnDTO turn,boolean requireLongTerm) {
        validateActor(turn,requireLongTerm,false);
    }
    public void validateArchiveActor(PersonTurnDTO turn) { validateActor(turn,false,true); }
    void validateActor(PersonTurnDTO turn,boolean requireLongTerm,boolean historical) {
        Integer retired=jdbc.queryForObject("SELECT COUNT(*) FROM ai_identity_cleanup WHERE account_id=? AND user_id=? AND generation=?",Integer.class,turn.getAccountId(),turn.getPersonId(),turn.getGeneration());
        if(retired!=null && retired>0)throw new RenException("人物身份已退役");
        List<Map<String,Object>> devices=jdbc.queryForList("SELECT d.user_id,d.agent_id,a.mem_model_id FROM ai_device d JOIN ai_agent a ON a.id=d.agent_id WHERE d.mac_address=? AND d.user_id=? AND d.agent_id=?",turn.getDeviceId(),turn.getAccountId(),turn.getAgentId());
        if(devices.size()!=1) throw new RenException("设备归属已变更");
        if(requireLongTerm && !"matched".equals(turn.getStatus())) throw new RenException("默认身份不使用云端记忆");
        if(requireLongTerm && (!enabled || !"Memory_bailian".equals(devices.get(0).get("mem_model_id")))) throw new RenException("当前智能体未开启长期记忆");
        Map<String,Object> state=identities.snapshot(turn.getAccountId());
        long version=((Number)state.get("directory_version")).longValue();
        if(historical ? turn.getDirectoryVersion()>version : version!=turn.getDirectoryVersion()) throw new RenException("人物目录已变更");
        if("default".equals(state.get("mode"))) {
            if(!"default".equals(turn.getStatus()) || !turn.getPersonId().equals(state.get("default_user_id")) || turn.getGeneration()!=((Number)state.get("default_generation")).longValue()) throw new RenException("默认身份已失效");
        } else {
            if(!"personal".equals(state.get("mode")))throw new RenException("本轮身份未确认");
            if(!"matched".equals(turn.getStatus()) || turn.getGeneration()!=0 || turn.getVoiceprintId()==null) throw new RenException("本轮身份未确认");
            Integer count=historical?jdbc.queryForObject("SELECT COUNT(*) FROM ai_user_identity WHERE account_id=? AND user_id=? AND status='active' AND kind='member'",Integer.class,turn.getAccountId(),turn.getPersonId()):jdbc.queryForObject("SELECT COUNT(*) FROM ai_agent_voice_print v JOIN ai_user_identity u ON u.account_id=v.creator AND u.user_id=v.user_id WHERE v.creator=? AND v.user_id=? AND v.id=? AND v.template_version=? AND v.binding_state='ready' AND u.status='active' AND u.kind='member'",Integer.class,turn.getAccountId(),turn.getPersonId(),turn.getVoiceprintId(),turn.getTemplateVersion());
            if(count==null || count!=1) throw new RenException("声纹绑定已失效");
        }
    }

    @Transactional
    public void material(PersonTurnDTO actor,String eventId,String kind,String content) {
        identities.lock(actor.getAccountId());
        validateActor(actor,"dialogue".equals(kind) && !"default".equals(actor.getStatus()),true);
        // A previously queued default turn may arrive after this policy is deployed.
        // Acknowledge it without creating a cloud entity or upload material.
        if("default".equals(actor.getStatus()) && Set.of("dialogue","habit_analysis").contains(kind))return;
        if("habit_analysis".equals(kind) && (!enabled || !"Memory_bailian".equals(jdbc.queryForObject("SELECT mem_model_id FROM ai_agent WHERE id=? AND user_id=?",String.class,actor.getAgentId(),actor.getAccountId()))))return;
        if(!Set.of("dialogue","behavior","habit_analysis","tool_result").contains(kind) || eventId==null || eventId.length()>128 || content==null || content.length()>65536) throw new RenException("材料格式无效");
        if("dialogue".equals(kind))ensureEntity(actor);
        int start=0,index=0;
        do {
            int end=Math.min(content.length(),start+Math.clamp(maxChars,2,16000));
            if(end<content.length() && Character.isHighSurrogate(content.charAt(end-1)))end--;
            String part=content.substring(start,end),partEvent=MemoryGatewayClient.sha(eventId+":"+index++);
            jdbc.update("INSERT IGNORE INTO ai_person_material(account_id,user_id,generation,agent_id,device_id,event_id,turn_id,kind,content) VALUES(?,?,?,?,?,?,?,?,?)",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId(),actor.getDeviceId(),partEvent,actor.getTurnId(),kind,part);
            start=end;
        } while(start<content.length());
    }

    private void ensureEntity(PersonTurnDTO actor) {
        String cloud=gateway.cloudUserId(actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        jdbc.update("INSERT IGNORE INTO ai_person_memory_entity(account_id,user_id,generation,cloud_user_id,daily_started_at) VALUES(?,?,?,?,UTC_TIMESTAMP())",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),cloud);
        Map<String,Object> entity=jdbc.queryForMap("SELECT state,cloud_user_id FROM ai_person_memory_entity WHERE account_id=? AND user_id=? AND generation=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        if(!"active".equals(entity.get("state")) || !cloud.equals(entity.get("cloud_user_id"))) throw new RenException("记忆实体已失效");
    }

    public Map<String,Object> search(PersonTurnDTO actor,String query) {
        validateActor(actor,true);
        var localChanges=jdbc.queryForList("SELECT id FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=? AND state='local_only'",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        if(!localChanges.isEmpty()) {
            ensureEntity(actor);
            jdbc.update("UPDATE ai_memory_override SET state='pending' WHERE account_id=? AND user_id=? AND generation=? AND state='local_only'",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        }
        if(query==null || query.isBlank() || query.length()>2048) throw new RenException("检索内容无效");
        List<Map<String,Object>> overrides=overrides(actor);
        boolean suppressed=overrides.stream().anyMatch(o->!"complete".equals(o.get("state")));
        Map<String,Object> response=suppressed?Map.of():gateway.request(actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),"POST","memory_nodes/search",Map.of("messages",List.of(Map.of("role","user","content",query)),"top_k",Math.clamp(topK,1,20),"plan_version","lite"),"turn-"+actor.getTurnId(),Duration.ofMillis(Math.clamp(searchTimeout,100,3000)));
        Object nodes=response.get("memory_nodes");
        StringBuilder text=new StringBuilder();
        if(nodes instanceof List<?> list) for(Object node:list) {
            if(!(node instanceof Map<?,?> map))continue;
            String value=Objects.toString(map.get("content"),Objects.toString(map.get("custom_content"),""));
            if(value.isBlank())continue;
            if(!suppressed)text.append(value).append('\n');
        }
        for(Map<String,Object> override:overrides) if("correct".equals(override.get("action")) && override.get("replacement")!=null)text.append(override.get("replacement")).append('\n');
        int end=Math.min(Math.clamp(factChars,128,8000),text.length());
        if(end>0 && end<text.length() && Character.isHighSurrogate(text.charAt(end-1)))end--;
        return Map.of("text",text.substring(0,end),"request_id",Objects.toString(response.get("request_id"),""));
    }

    @Transactional
    public void override(PersonTurnDTO actor,String action,String match,String replacement) {
        identities.lock(actor.getAccountId());validateActor(actor,false);
        if(!Set.of("forget","correct").contains(action) || match==null || match.isBlank() || match.length()>1024 || replacement!=null && replacement.length()>2048)throw new RenException("更正内容无效");
        boolean longTerm="matched".equals(actor.getStatus()) && enabled && "Memory_bailian".equals(jdbc.queryForObject("SELECT mem_model_id FROM ai_agent WHERE id=? AND user_id=?",String.class,actor.getAgentId(),actor.getAccountId()));
        if(longTerm)ensureEntity(actor);
        // Invalidate all old turn sources, including adjacent replies, before cloud cleanup.
        jdbc.update("UPDATE ai_agent_chat_history SET recall_allowed=FALSE WHERE account_id=? AND person_id=? AND default_generation=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        if("*".equals(match))jdbc.update("DELETE FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        else jdbc.update("DELETE FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=? AND match_text=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),match);
        String overrideId=AccountIdentityStateService.newId();
        jdbc.update("INSERT INTO ai_memory_override(id,account_id,user_id,generation,action,match_text,replacement) VALUES(?,?,?,?,?,?,?)",overrideId,actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),action,match,replacement);
        if(!longTerm)jdbc.update("UPDATE ai_memory_override SET state='local_only' WHERE id=?",overrideId);
        jdbc.update("DELETE FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=? AND match_text=? AND state='complete'",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),match);
        if("*".equals(match)) jdbc.update("DELETE FROM ai_person_material WHERE account_id=? AND user_id=? AND generation=? AND kind IN('dialogue','habit_analysis')",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        else jdbc.update("DELETE FROM ai_person_material WHERE account_id=? AND user_id=? AND generation=? AND kind IN('dialogue','habit_analysis') AND LOCATE(?,content)>0",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),match);
        jdbc.update("UPDATE ai_memory_task SET state='cancelled',payload=NULL WHERE account_id=? AND user_id=? AND generation=? AND state IN('pending','retry')",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
    }

    public List<Map<String,Object>> overrides(PersonTurnDTO actor) {
        return jdbc.queryForList("SELECT action,match_text,replacement,state FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
    }
    public Map<String,Object> background(PersonTurnDTO actor) {
        validateActor(actor,true);
        if(!portraitsEnabled() || !overrides(actor).isEmpty())return Map.of("text","");
        Map<String,Object> profile=gateway.request(actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),"GET","profile_schemas/"+portraitSchema+"/user_profile",null,null,Duration.ofSeconds(3));
        try {String value=json.writeValueAsString(profile.getOrDefault("user_profile",Map.of()));return Map.of("text",value.substring(0,Math.min(1500,value.length())));}
        catch(Exception e){return Map.of("text","");}
    }
    public Map<String,Object> adminRead(Long account,String person,long generation,int page) {
        if(page<1)throw new RenException("页码无效");
        Integer count=jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_memory_entity WHERE account_id=? AND user_id=? AND generation=?",Integer.class,account,person,generation);
        if(count==null || count!=1)throw new RenException("记忆实体不存在");
        return gateway.request(account,person,generation,"GET","memory_nodes?page_size=50&page_num="+page,null,null,Duration.ofSeconds(3));
    }
    public Map<String,Object> adminPortrait(Long account,String person,long generation) {
        Integer count=jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_memory_entity WHERE account_id=? AND user_id=? AND generation=?",Integer.class,account,person,generation);
        if(count==null || count!=1)throw new RenException("记忆实体不存在");
        if(!portraitsEnabled())return Map.of("enabled",false,"reason","individual_delete_and_storage_count_not_verified");
        return gateway.request(account,person,generation,"GET","profile_schemas/"+portraitSchema+"/user_profile",null,null,Duration.ofSeconds(3));
    }
}
