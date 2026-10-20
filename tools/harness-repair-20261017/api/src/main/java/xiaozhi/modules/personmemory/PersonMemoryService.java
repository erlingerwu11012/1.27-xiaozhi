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
        validateActor(actor,Set.of("dialogue","dialogue_assistant","dialogue_end","tool_result").contains(kind) && !"default".equals(actor.getStatus()),true);
        // A previously queued default turn may arrive after this policy is deployed.
        // Acknowledge it without creating a cloud entity or upload material.
        if("default".equals(actor.getStatus()) && Set.of("dialogue","dialogue_assistant","dialogue_end","tool_result","habit_analysis").contains(kind))return;
        if("habit_analysis".equals(kind) && (!enabled || !"Memory_bailian".equals(jdbc.queryForObject("SELECT mem_model_id FROM ai_agent WHERE id=? AND user_id=?",String.class,actor.getAgentId(),actor.getAccountId()))))return;
        if(!Set.of("dialogue","dialogue_assistant","dialogue_end","behavior","habit_analysis","tool_result").contains(kind) || eventId==null || eventId.length()>128 || content==null || content.length()>65536) throw new RenException("材料格式无效");
        if(Set.of("dialogue","dialogue_assistant","dialogue_end","tool_result").contains(kind))ensureEntity(actor);
        Long suppression=jdbc.queryForObject("SELECT MAX(UNIX_TIMESTAMP(created_at)*1000) FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=? AND match_text='*'",Long.class,actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        if(suppression!=null && (actor.getCapturedAt()==null || actor.getCapturedAt()<=suppression+1000))return;
        var affected=jdbc.queryForList("SELECT match_text,UNIX_TIMESTAMP(created_at)*1000 AS changed_at FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=? AND match_text<>'*'",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        if(affected.stream().anyMatch(change->content.contains(Objects.toString(change.get("match_text"),"")) && (actor.getCapturedAt()==null || actor.getCapturedAt()<=((Number)change.get("changed_at")).longValue()+1000)))return;
        int start=0,index=0;
        int remainingTokens="dialogue".equals(kind)?MemoryMaterialPolicy.userTokens(content):0;
        do {
            int end=Math.min(content.length(),start+Math.clamp(maxChars,2,16000));
            if(end<content.length() && Character.isHighSurrogate(content.charAt(end-1)))end--;
            String part=content.substring(start,end),partEvent=MemoryGatewayClient.sha(eventId+":"+index++);
            jdbc.update("INSERT IGNORE INTO ai_person_material(account_id,user_id,generation,agent_id,device_id,event_id,turn_id,kind,content,user_tokens,token_version) VALUES(?,?,?,?,?,?,?,?,?,?,1)",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId(),actor.getDeviceId(),partEvent,actor.getTurnId(),kind,part,end==content.length()?remainingTokens:0);
            start=end;
        } while(start<content.length());
    }

    @Transactional
    public Map<String,Object> add(PersonTurnDTO actor,String fact) {
        identities.lock(actor.getAccountId());validateActor(actor,false);
        if(fact==null || fact.isBlank() || fact.length()>1024 || !RecentArchiveService.factualUser(fact,1) || !fact.strip().equals(RecentArchiveService.normalizeFact(fact)))throw new RenException("只能保存明确的单条事实");
        String normalized=fact.strip();
        boolean cloud="matched".equals(actor.getStatus()) && enabled && "Memory_bailian".equals(jdbc.queryForObject("SELECT mem_model_id FROM ai_agent WHERE id=? AND user_id=?",String.class,actor.getAgentId(),actor.getAccountId()));
        if(cloud)ensureEntity(actor);
        String event=MemoryGatewayClient.sha("explicit-fact:"+actor.getTurnId());
        jdbc.update("INSERT IGNORE INTO ai_person_material(account_id,user_id,generation,agent_id,device_id,event_id,turn_id,kind,content,user_tokens,token_version) VALUES(?,?,?,?,?,?,?,'explicit_fact',?,?,1)",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId(),actor.getDeviceId(),event,actor.getTurnId(),normalized,MemoryMaterialPolicy.userTokens(normalized));
        var rows=jdbc.queryForList("SELECT id,content,recall_allowed FROM ai_person_material WHERE account_id=? AND user_id=? AND generation=? AND event_id=? AND agent_id=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),event,actor.getAgentId());
        if(rows.size()!=1 || !normalized.equals(rows.get(0).get("content")) || !Boolean.TRUE.equals(rows.get(0).get("recall_allowed")))throw new RenException("该请求已变化或保存状态未确认");
        return Map.of("local_applied",true,"operation","add","status","completed","record_id","material:"+rows.get(0).get("id"),"version",MemoryGatewayClient.sha(normalized),"fact",normalized,"cloud_sync",cloud?"pending":"disabled");
    }

    private void ensureEntity(PersonTurnDTO actor) {
        String cloud=gateway.cloudUserId(actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        jdbc.update("INSERT IGNORE INTO ai_person_memory_entity(account_id,user_id,generation,cloud_user_id,daily_started_at) VALUES(?,?,?,?,NULL)",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),cloud);
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
        List<Map<String,Object>> items=new ArrayList<>();Set<String> seen=new HashSet<>();int chars=0;
        if(nodes instanceof List<?> list) for(Object node:list) {
            if(!(node instanceof Map<?,?> map))continue;
            String value=RecentArchiveService.normalizeFact(Objects.toString(map.get("content"),Objects.toString(map.get("custom_content"),"")));
            if(!RecentArchiveService.factualUser(value))continue;
            if(value.isBlank() || value.length()>1024 || value.contains("[来源:") || value.contains("[来源：") || value.contains("[本轮可信") || value.contains("\"tool_calls\"") || !seen.add(value))continue;
            if(chars+value.length()>Math.clamp(factChars,128,8000))continue;
            Object id=map.get("id");if(id==null)id=map.get("memory_node_id");
            if(id==null)continue;
            items.add(Map.of("record_id","cloud:"+id,"text",value,"source","cloud_user_fact","version",MemoryGatewayClient.sha(value),"owner",actor.getPersonId()));chars+=value.length();
        }
        for(Map<String,Object> override:overrides) if("correct".equals(override.get("action")) && !"superseded".equals(override.get("state")) && override.get("replacement")!=null){
            String value=override.get("replacement").toString();
            if(value.length()<=1024 && seen.add(value))items.add(Map.of("record_id","override:"+override.get("id"),"text",value,"source","local_override","version",MemoryGatewayClient.sha(value),"owner",actor.getPersonId()));
        }
        String text=items.stream().map(i->i.get("text").toString()).collect(java.util.stream.Collectors.joining("\n"));
        return Map.of("text",text,"items",items,"status",items.isEmpty()?(suppressed?"suppressed":"not_found"):"found","request_id",Objects.toString(response.get("request_id"),""));
    }

    @Transactional
    public Map<String,Object> override(PersonTurnDTO actor,String action,String match,String replacement) {
        identities.lock(actor.getAccountId());validateActor(actor,false);
        if("correct".equals(action) && (replacement==null || replacement.isBlank()))throw new RenException("新的记忆内容不能为空");
        if(!Set.of("forget","correct").contains(action) || match==null || match.isBlank() || match.length()>1024 || replacement!=null && replacement.length()>2048)throw new RenException("更正内容无效");
        boolean longTerm="matched".equals(actor.getStatus()) && enabled && "Memory_bailian".equals(jdbc.queryForObject("SELECT mem_model_id FROM ai_agent WHERE id=? AND user_id=?",String.class,actor.getAgentId(),actor.getAccountId()));
        if(longTerm)ensureEntity(actor);
        // Suppress only affected facts. Keep raw material as an auditable record.
        if("*".equals(match))jdbc.update("UPDATE ai_agent_chat_history SET recall_allowed=FALSE WHERE account_id=? AND person_id=? AND default_generation=? AND agent_id=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId());
        else jdbc.update("UPDATE ai_agent_chat_history SET recall_allowed=FALSE WHERE account_id=? AND person_id=? AND default_generation=? AND agent_id=? AND content=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId(),match);
        if("*".equals(match))jdbc.update("DELETE FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        else jdbc.update("DELETE FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=? AND match_text=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),match);
        jdbc.update("UPDATE ai_memory_override SET state='superseded' WHERE account_id=? AND user_id=? AND generation=? AND replacement IS NOT NULL AND replacement=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),match);
        String overrideId=AccountIdentityStateService.newId();
        // Capture a causal boundary under the account lock. Timestamp precision
        // must not suppress an explicit fact saved after this operation.
        Long materialCutoff=jdbc.queryForObject("SELECT COALESCE(MAX(id),0) FROM ai_person_material WHERE account_id=? AND user_id=? AND generation=?",Long.class,actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        Long archiveCutoff=jdbc.queryForObject("SELECT COALESCE(MAX(id),0) FROM ai_agent_chat_history WHERE account_id=? AND person_id=? AND default_generation=?",Long.class,actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        jdbc.update("INSERT INTO ai_memory_override(id,account_id,user_id,generation,action,match_text,replacement,material_cutoff_id,archive_cutoff_id) VALUES(?,?,?,?,?,?,?,?,?)",overrideId,actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),action,match,replacement,materialCutoff,archiveCutoff);
        if(!longTerm)jdbc.update("UPDATE ai_memory_override SET state='local_only' WHERE id=?",overrideId);
        jdbc.update("DELETE FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=? AND match_text=? AND state='complete'",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),match);
        if("*".equals(match))jdbc.update("UPDATE ai_person_material SET recall_allowed=FALSE WHERE account_id=? AND user_id=? AND generation=? AND agent_id=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId());
        else jdbc.update("UPDATE ai_person_material SET recall_allowed=FALSE WHERE account_id=? AND user_id=? AND generation=? AND agent_id=? AND content=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId(),match);
        jdbc.update("UPDATE ai_memory_task SET state='cancelled',payload=NULL WHERE account_id=? AND user_id=? AND generation=? AND state IN('pending','retry')",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        Integer stored=jdbc.queryForObject("SELECT COUNT(*) FROM ai_memory_override WHERE id=? AND account_id=? AND user_id=? AND action=? AND match_text=?",Integer.class,overrideId,actor.getAccountId(),actor.getPersonId(),action,match);
        if(stored==null || stored!=1)throw new RenException("记忆修改保存未确认");
        return Map.of("local_applied",true,"operation",action,"operation_id",overrideId,"cloud_sync",longTerm?"pending":"disabled","status","completed","record_id","override:"+overrideId,"version",MemoryGatewayClient.sha(replacement==null?"":replacement));
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
