package xiaozhi.modules.personmemory;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PreDestroy;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;
import xiaozhi.modules.useridentity.service.AccountIdentityStateService;

/** Durable batches and leases. Unknown submissions are never automatically resubmitted. */
@Slf4j
@Component
@RequiredArgsConstructor
public class MemoryDailyWorker {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final TransactionTemplate transactions;
    private final MemoryGatewayClient gateway;
    private final PersonMemoryService service;
    private final xiaozhi.modules.face.service.FaceProxyService faces;
    @Value("${memory.material.min-user-tokens:10000}") private int minUserTokens=10000;
    @Value("${memory.portrait.schema-id:}") private String schemaId;
    private final AtomicBoolean running=new AtomicBoolean();
    private final ExecutorService executor=Executors.newSingleThreadExecutor(r->{Thread thread=new Thread(r,"person-memory-worker");thread.setDaemon(true);return thread;});

    @PreDestroy public void close(){executor.shutdown();}
    @Scheduled(cron="0 0 3 * * *",zone="Asia/Shanghai")
    public void beginDaily() {
        if(!service.enabled())return;
        captureDailyBoundary();
        jdbc.update("UPDATE ai_memory_override SET state='ready' WHERE state='pending'");
    }

    @Scheduled(fixedDelay=3000,initialDelay=10000)
    public void tick() {
        if(!running.compareAndSet(false,true))return;
        executor.submit(()->{try {step();}catch(Exception e){log.warn("memory worker deferred: {}",e.getClass().getSimpleName());}finally{running.set(false);}});
    }

    public void step() {
        catchUpDaily();
        // Default identities use local summaries only. Cancel unsent legacy
        // extraction work while leaving accepted/review events to reconcile.
        jdbc.update("UPDATE ai_memory_task SET state='cancelled',payload=NULL,lease_until=NULL WHERE generation>0 AND kind='extract' AND state IN('pending','retry')");
        // Resume an unfinished daily window after a restart, before generating another task.
        List<Map<String,Object>> entities=service.enabled()?jdbc.queryForList("SELECT * FROM ai_person_memory_entity WHERE state='active' AND generation=0 AND daily_watermark>processed_watermark ORDER BY account_id,user_id LIMIT 20"):List.of();
        for(Map<String,Object> entity:entities)buildBatch(entity);
        List<Map<String,Object>> tasks=jdbc.queryForList("SELECT * FROM ai_memory_task WHERE state IN("+(service.enabled()?"'pending','retry','accepted','review'":"'accepted','review'")+") AND (next_attempt_at IS NULL OR next_attempt_at<=NOW()) AND (lease_until IS NULL OR lease_until<NOW()) ORDER BY created_at LIMIT 1");
        if(!tasks.isEmpty()) {
            Map<String,Object> task=tasks.get(0);String id=(String)task.get("id");
            if(jdbc.update("UPDATE ai_memory_task SET lease_until=DATE_ADD(NOW(),INTERVAL 3 MINUTE) WHERE id=? AND (lease_until IS NULL OR lease_until<NOW())",id)==1)runTask(task);
        }
        cleanupOne();
        cleanupFaceOne();
        synchronizeOverrideOne();
        jdbc.update("UPDATE ai_identity_cleanup c SET local_done=TRUE WHERE NOT EXISTS(SELECT 1 FROM ai_identity_cleanup_device d WHERE d.cleanup_id=c.id AND d.confirmed_at IS NULL)");
        jdbc.update("UPDATE ai_identity_cleanup SET state='complete' WHERE cloud_done=TRUE AND portrait_done=TRUE AND local_done=TRUE");
    }

    void buildBatch(Map<String,Object> entity) {
        if(((Number)entity.get("generation")).longValue()!=0)return;
        transactions.executeWithoutResult(status->{
            Long account=((Number)entity.get("account_id")).longValue();String person=(String)entity.get("user_id");long gen=((Number)entity.get("generation")).longValue();
            Map<String,Object> current=jdbc.queryForMap("SELECT * FROM ai_person_memory_entity WHERE account_id=? AND user_id=? AND generation=? FOR UPDATE",account,person,gen);
            long after=((Number)current.get("processed_watermark")).longValue(),until=((Number)current.get("daily_watermark")).longValue();
            if(!"active".equals(current.get("state")) || until<=after)return;
            Integer corrections=jdbc.queryForObject("SELECT COUNT(*) FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=? AND state<>'complete'",Integer.class,account,person,gen);
            if(corrections!=null && corrections>0)return;
            Integer pending=jdbc.queryForObject("SELECT COUNT(*) FROM ai_memory_task WHERE account_id=? AND user_id=? AND generation=? AND state NOT IN('complete','cancelled')",Integer.class,account,person,gen);
            if(pending!=null && pending>0)return;
            List<Map<String,Object>> materials=jdbc.queryForList("SELECT m.* FROM ai_person_material m JOIN ai_agent a ON a.id=m.agent_id AND a.user_id=m.account_id WHERE m.account_id=? AND m.user_id=? AND m.generation=? AND m.id>? AND m.id<=? AND m.recall_allowed=TRUE AND m.kind IN('dialogue','dialogue_assistant','dialogue_end','tool_result','habit_analysis') AND a.mem_model_id='Memory_bailian' ORDER BY m.id",account,person,gen,after,until);
            // A turn submitted just before the boundary is not acknowledged until
            // its durable end marker is present. Never advance past an unfinished turn.
            Set<String> closed=new HashSet<>();for(var row:materials)if("dialogue_end".equals(row.get("kind")))closed.add(Objects.toString(row.get("turn_id"),""));
            long incomplete=materials.stream().filter(row->"dialogue".equals(row.get("kind")) && ((Number)row.getOrDefault("token_version",0)).intValue()>0 && !closed.contains(Objects.toString(row.get("turn_id"),""))).mapToLong(row->((Number)row.get("id")).longValue()).min().orElse(Long.MAX_VALUE);
            materials.removeIf(row->((Number)row.get("id")).longValue()>=incomplete);
            if(materials.isEmpty())return;
            long tokens=materials.stream().filter(m->"dialogue".equals(m.get("kind"))).mapToLong(m->{long n=((Number)m.getOrDefault("user_tokens",0)).longValue();return ((Number)m.getOrDefault("token_version",0)).intValue()>0?n:MemoryMaterialPolicy.userTokens(Objects.toString(m.get("content"),""));}).sum();
            if(tokens<Math.max(1,minUserTokens))return;
            Set<String> agents=new HashSet<>();for(var material:materials)agents.add(Objects.toString(material.get("agent_id"),""));
            List<Map<String,String>> messages=MemoryMaterialPolicy.messages(materials,json);
            long watermark=((Number)materials.get(materials.size()-1).get("id")).longValue();
            try {
                Map<String,Object> body=new HashMap<>();body.put("messages",messages);body.put("_material_agents",agents);
                if(service.portraitsEnabled())body.put("profile_schema",schemaId);
                String payload=json.writeValueAsString(body),id=AccountIdentityStateService.newId();
                jdbc.update("INSERT INTO ai_memory_task(id,account_id,user_id,generation,kind,watermark,payload_hash,payload) VALUES(?,?,?,?,'extract',?,?,?) ON DUPLICATE KEY UPDATE payload=IF(state='cancelled',VALUES(payload),payload),payload_hash=IF(state='cancelled',VALUES(payload_hash),payload_hash),next_attempt_at=IF(state='cancelled',NULL,next_attempt_at),state=IF(state='cancelled','pending',state)",id,account,person,gen,watermark,MemoryGatewayClient.sha(payload),payload);
            }catch(Exception e){throw new IllegalStateException("batch_serialization_failed",e);}
        });
    }

    void runTask(Map<String,Object> task) {
        String id=(String)task.get("id"),person=(String)task.get("user_id");Long account=((Number)task.get("account_id")).longValue();long gen=((Number)task.get("generation")).longValue();
        try {
            String state=(String)task.get("state");
            if("review".equals(state)) {
                int attempt=((Number)task.get("attempts")).intValue();
                Map<String,Object> recovered=gateway.operationStatus(account,person,gen,id+"-"+attempt);
                if("complete".equals(recovered.get("state")) && recovered.get("result") instanceof Map<?,?> result) {
                    String event=Objects.toString(result.get("event_id"),"");
                    if(!event.isBlank())jdbc.update("UPDATE ai_memory_task SET state='accepted',event_id=?,lease_until=NULL,next_attempt_at=NOW() WHERE id=?",event,id);
                    else jdbc.update("UPDATE ai_memory_task SET lease_until=NULL,next_attempt_at=DATE_ADD(NOW(),INTERVAL 5 MINUTE) WHERE id=?",id);
                } else if("prepared".equals(recovered.get("state")) || "rejected".equals(recovered.get("state")) ||
                    "complete".equals(recovered.get("state")) && recovered.get("status") instanceof Number status && status.intValue()>=400 && status.intValue()<500 && status.intValue()!=408 && status.intValue()!=429) {
                    jdbc.update("UPDATE ai_memory_task SET state='retry',lease_until=NULL,next_attempt_at=DATE_ADD(NOW(),INTERVAL 5 MINUTE) WHERE id=?",id);
                } else jdbc.update("UPDATE ai_memory_task SET lease_until=NULL,next_attempt_at=DATE_ADD(NOW(),INTERVAL 5 MINUTE) WHERE id=?",id);
                return;
            }
            if("accepted".equals(state)) {
                Map<String,Object> event=gateway.request(account,person,gen,"GET","events/"+task.get("event_id"),null,null,Duration.ofSeconds(15));
                Set<String> states=eventStates(event);
                if(states.contains("FAILED") || states.contains("UNRECORDED")) {
                    jdbc.update("UPDATE ai_memory_task SET state='failed',last_error='upstream_extraction_failed',lease_until=NULL WHERE id=?",id);return;
                }
                if(!states.isEmpty() && states.stream().allMatch("SUCCEEDED"::equals)){complete(task);return;}
                jdbc.update("UPDATE ai_memory_task SET lease_until=NULL,next_attempt_at=DATE_ADD(NOW(),INTERVAL 20 SECOND) WHERE id=?",id);return;
            }
            Integer active=jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_memory_entity WHERE account_id=? AND user_id=? AND generation=? AND state='active'",Integer.class,account,person,gen);
            if(active==null || active!=1){jdbc.update("UPDATE ai_memory_task SET state='cancelled',payload=NULL,lease_until=NULL WHERE id=?",id);return;}
            Integer longTerm=jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_material m JOIN ai_agent a ON a.id=m.agent_id AND a.user_id=m.account_id WHERE m.account_id=? AND m.user_id=? AND m.generation=? AND m.id<=? AND a.mem_model_id='Memory_bailian'",Integer.class,account,person,gen,task.get("watermark"));
            if(longTerm==null || longTerm==0){jdbc.update("UPDATE ai_memory_task SET state='retry',lease_until=NULL,next_attempt_at=DATE_ADD(NOW(),INTERVAL 1 HOUR) WHERE id=?",id);return;}
            Map<String,Object> body=json.readValue((String)task.get("payload"),new TypeReference<Map<String,Object>>(){});
            Object materialAgents=body.remove("_material_agents");
            if(materialAgents instanceof Collection<?> agents) for(Object agent:agents) {
                Integer enabled=jdbc.queryForObject("SELECT COUNT(*) FROM ai_agent WHERE id=? AND user_id=? AND mem_model_id='Memory_bailian'",Integer.class,agent,account);
                if(enabled==null || enabled==0){jdbc.update("UPDATE ai_memory_task SET state='cancelled',payload=NULL,lease_until=NULL WHERE id=?",id);return;}
            }
            // Commit the attempt marker before network I/O. A crashed submit enters review below.
            int attempt=((Number)task.get("attempts")).intValue()+1;
            jdbc.update("UPDATE ai_memory_task SET state='submitting',attempts=? WHERE id=?",attempt,id);
            if(body.containsKey("profile_schema"))jdbc.update("UPDATE ai_person_memory_entity SET portrait_written=TRUE,portrait_schema_id=? WHERE account_id=? AND user_id=? AND generation=?",schemaId,account,person,gen);
            Map<String,Object> accepted=gateway.request(account,person,gen,"POST","add-async",body,id+"-"+attempt,Duration.ofSeconds(80));
            String event=Objects.toString(accepted.get("event_id"),"");
            if(event.isBlank())throw new MemoryGatewayClient.GatewayFailure(599);
            jdbc.update("UPDATE ai_memory_task SET state='accepted',event_id=?,lease_until=NULL,next_attempt_at=DATE_ADD(NOW(),INTERVAL 10 SECOND) WHERE id=?",event,id);
        } catch(MemoryGatewayClient.GatewayFailure e) {
            if("accepted".equals(task.get("state")) || "review".equals(task.get("state"))) {
                jdbc.update("UPDATE ai_memory_task SET lease_until=NULL,last_error=?,next_attempt_at=DATE_ADD(NOW(),INTERVAL 5 MINUTE) WHERE id=?",e.getMessage(),id);return;
            }
            String next=Set.of(402,403,503).contains(e.status())?"retry":"review";
            // A gateway 503 may mean settlement pending after upstream acceptance. Reconcile the same key first.
            if(e.status()==503)next="review";
            jdbc.update("UPDATE ai_memory_task SET state=?,last_error=?,lease_until=NULL,next_attempt_at=DATE_ADD(NOW(),INTERVAL 5 MINUTE) WHERE id=?",next,e.getMessage(),id);
        } catch(Exception e) {
            jdbc.update("UPDATE ai_memory_task SET state='review',last_error=?,lease_until=NULL WHERE id=?",e.getClass().getSimpleName(),id);
        }
    }

    void complete(Map<String,Object> task) {
        transactions.executeWithoutResult(status->{
            Long account=((Number)task.get("account_id")).longValue();String person=(String)task.get("user_id");long gen=((Number)task.get("generation")).longValue(),mark=((Number)task.get("watermark")).longValue();
            jdbc.update("UPDATE ai_memory_task SET state='complete',payload=NULL,lease_until=NULL WHERE id=?",task.get("id"));
            jdbc.update("UPDATE ai_person_memory_entity SET processed_watermark=GREATEST(processed_watermark,?) WHERE account_id=? AND user_id=? AND generation=? AND state='active'",mark,account,person,gen);
            jdbc.update("DELETE FROM ai_person_material WHERE account_id=? AND user_id=? AND generation=? AND id<=? AND kind IN('dialogue','dialogue_assistant','dialogue_end','tool_result','habit_analysis')",account,person,gen,mark);
        });
    }

    static Set<String> eventStates(Object value) {
        Set<String> result=new HashSet<>();
        if(value instanceof Map<?,?> map){Object state=map.get("status");if(state instanceof String s)result.add(s);for(String key:List.of("events","event"))if(map.containsKey(key))result.addAll(eventStates(map.get(key)));}
        else if(value instanceof List<?> list)for(Object item:list)result.addAll(eventStates(item));
        return result;
    }

    void cleanupOne() {
        // A crashed submit has no safely repeatable upstream request: keep it for reconciliation.
        jdbc.update("UPDATE ai_memory_task SET state='review',last_error='process_recovery' WHERE state='submitting' AND lease_until<NOW()");
        List<Map<String,Object>> tasks=jdbc.queryForList("SELECT * FROM ai_identity_cleanup WHERE cloud_done=FALSE AND (lease_until IS NULL OR lease_until<NOW()) ORDER BY created_at LIMIT 1");
        if(tasks.isEmpty())return;
        Map<String,Object> task=tasks.get(0);String id=(String)task.get("id"),person=(String)task.get("user_id");Long account=((Number)task.get("account_id")).longValue();long gen=((Number)task.get("generation")).longValue();
        if(jdbc.update("UPDATE ai_identity_cleanup SET lease_until=DATE_ADD(NOW(),INTERVAL 3 MINUTE),attempts=attempts+1 WHERE id=? AND (lease_until IS NULL OR lease_until<NOW())",id)!=1)return;
        try {
            Integer entityCount=jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_memory_entity WHERE account_id=? AND user_id=? AND generation=?",Integer.class,account,person,gen);
            if(entityCount!=null && entityCount==0) {
                jdbc.update("UPDATE ai_identity_cleanup SET cloud_done=TRUE,portrait_done=TRUE,lease_until=NULL WHERE id=?",id);return;
            }
            gateway.request(account,person,gen,"POST","entities/retire",Map.of(),"retire-"+id,Duration.ofSeconds(3));
            Map<String,Object> listed=gateway.request(account,person,gen,"GET","memory_nodes?page_num=1&page_size=50",null,null,Duration.ofSeconds(10));
            if(listed.get("memory_nodes") instanceof List<?> nodes && !nodes.isEmpty()) {
                for(Object node:nodes)if(node instanceof Map<?,?> map){String nodeId=Objects.toString(map.get("memory_node_id"),Objects.toString(map.get("id"),""));if(!nodeId.isBlank())gateway.request(account,person,gen,"DELETE","memory_nodes/"+nodeId,null,"delete-"+nodeId,Duration.ofSeconds(10));}
                jdbc.update("UPDATE ai_identity_cleanup SET lease_until=NULL WHERE id=?",id);return;
            }
            Integer pending=jdbc.queryForObject("SELECT COUNT(*) FROM ai_memory_task WHERE account_id=? AND user_id=? AND generation=? AND state IN('accepted','submitting','review')",Integer.class,account,person,gen);
            Integer portraits=jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_memory_entity WHERE account_id=? AND user_id=? AND generation=? AND portrait_written=TRUE",Integer.class,account,person,gen);
            if((pending!=null && pending>0) || (portraits!=null && portraits>0)) {
                jdbc.update("UPDATE ai_identity_cleanup SET last_error='late_event_or_portrait_pending',lease_until=DATE_ADD(NOW(),INTERVAL 5 MINUTE) WHERE id=?",id);return;
            }
            gateway.request(account,person,gen,"POST","entities/cleanup-complete",Map.of(),"complete-"+id,Duration.ofSeconds(3));
            jdbc.update("UPDATE ai_identity_cleanup SET cloud_done=TRUE,portrait_done=TRUE,lease_until=NULL WHERE id=?",id);
        } catch(Exception e){jdbc.update("UPDATE ai_identity_cleanup SET last_error=?,lease_until=DATE_ADD(NOW(),INTERVAL 5 MINUTE) WHERE id=?",e.getClass().getSimpleName(),id);}
    }

    void catchUpDaily() {
        if(!service.enabled())return;
        var now=java.time.ZonedDateTime.now(java.time.ZoneId.of("Asia/Shanghai"));
        if(now.getHour()<3)return;
        String boundary=now.toLocalDate().atTime(3,0).atZone(now.getZone()).withZoneSameInstant(java.time.ZoneOffset.UTC).format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
        captureDailyBoundary();
        // Overdue deletions can catch up; new daytime overrides wait for 03:00.
        // Compare epoch seconds: @@session.time_zone can be SYSTEM, which is not
        // a valid CONVERT_TZ zone and would leave overdue work pending forever.
        long epoch=now.toLocalDate().atTime(3,0).atZone(now.getZone()).toEpochSecond();
        jdbc.update("UPDATE ai_memory_override SET state='ready' WHERE state='pending' AND UNIX_TIMESTAMP(created_at)<?",epoch);
    }

    void captureDailyBoundary() {
        var now=java.time.ZonedDateTime.now(java.time.ZoneId.of("Asia/Shanghai"));
        var day=now.getHour()<3?now.toLocalDate().minusDays(1):now.toLocalDate();
        long cutoff=day.atTime(3,0).atZone(now.getZone()).toEpochSecond();
        jdbc.update("UPDATE ai_person_memory_entity e SET daily_watermark=COALESCE((SELECT MAX(m.id) FROM ai_person_material m WHERE m.account_id=e.account_id AND m.user_id=e.user_id AND m.generation=e.generation AND UNIX_TIMESTAMP(m.created_at)<?),processed_watermark),daily_started_at=FROM_UNIXTIME(?) WHERE state='active' AND generation=0 AND (daily_started_at IS NULL OR UNIX_TIMESTAMP(daily_started_at)<?)",cutoff,cutoff,cutoff);
    }

    void synchronizeOverrideOne() {
        var tasks=jdbc.queryForList("SELECT * FROM ai_memory_override WHERE state='ready' ORDER BY created_at LIMIT 1");
        if(tasks.isEmpty())return;
        var task=tasks.get(0);Long account=((Number)task.get("account_id")).longValue();String person=(String)task.get("user_id"),id=(String)task.get("id"),match=(String)task.get("match_text");long gen=((Number)task.get("generation")).longValue();
        if(gen>0){jdbc.update("UPDATE ai_memory_override SET state='local_only' WHERE id=?",id);return;}
        Integer waiting=jdbc.queryForObject("SELECT COUNT(*) FROM ai_memory_task WHERE account_id=? AND user_id=? AND generation=? AND state IN('accepted','submitting','review') AND created_at<=?",Integer.class,account,person,gen,task.get("created_at"));
        if(waiting!=null && waiting>0)return;
        try {
            int page=((Number)task.get("scan_page")).intValue();boolean completeScan=false;long total=0;
            for(int batch=0;batch<20;batch++) {
                var listed=gateway.request(account,person,gen,"GET","memory_nodes?page_size=50&page_num="+page,null,null,Duration.ofSeconds(3));
                if(!(listed.get("total") instanceof Number count))throw new IllegalStateException("missing_memory_total");
                total=count.longValue();
                if(!(listed.get("memory_nodes") instanceof List<?> nodes))throw new IllegalStateException("invalid_memory_list");
                if(nodes.isEmpty()){completeScan=true;break;}
                boolean removed=false;
                for(Object item:nodes)if(item instanceof Map<?,?> node) {
                    String text=Objects.toString(node.get("content"),""),nodeId=Objects.toString(node.get("memory_node_id"),"");
                    if(!nodeId.isBlank() && ("*".equals(match) || text.contains(match))) {
                        gateway.request(account,person,gen,"DELETE","memory_nodes/"+nodeId,null,null,Duration.ofSeconds(3));removed=true;
                        jdbc.update("UPDATE ai_memory_override SET matched_count=matched_count+1 WHERE id=?",id);
                    }
                }
                if(removed)return; // Revisit same page after deletion; pagination shifts.
                if(nodes.size()<50){completeScan=true;break;}
                page++;
                jdbc.update("UPDATE ai_memory_override SET scan_page=? WHERE id=?",page,id);
                if(batch==19)return; // Keep suppression until a complete scan succeeds.
            }
            if(!completeScan)return;
            Integer matched=jdbc.queryForObject("SELECT matched_count FROM ai_memory_override WHERE id=?",Integer.class,id);
            if(total>0 && !"*".equals(match) && (matched==null || matched==0)) {
                jdbc.update("UPDATE ai_memory_override SET last_error='exact_fact_match_not_found',scan_page=1 WHERE id=?",id);return;
            }
            transactions.executeWithoutResult(status->{
                if("correct".equals(task.get("action")) && task.get("replacement") instanceof String replacement && !replacement.isBlank()) {
                    var source=jdbc.queryForList("SELECT d.id AS device_id,a.id AS agent_id FROM ai_device d JOIN ai_agent a ON a.id=d.agent_id AND a.user_id=d.user_id WHERE d.user_id=? AND a.mem_model_id='Memory_bailian' ORDER BY d.id LIMIT 1",account);
                    // A correction is its own extraction material; no stale actor
                    // or transcript is reassigned to another person.
                    if(source.isEmpty())throw new IllegalStateException("correction_long_term_source_unavailable");
                    jdbc.update("INSERT IGNORE INTO ai_person_material(account_id,user_id,generation,agent_id,device_id,event_id,turn_id,kind,content) VALUES(?,?,?,?,?,?,?,'dialogue',?)",account,person,gen,source.get(0).get("agent_id"),source.get(0).get("device_id"),"correction-"+id,id,replacement);
                }
                jdbc.update("UPDATE ai_memory_override SET state='complete' WHERE id=? AND state='ready'",id);
            });
        }catch(Exception e){log.warn("memory correction deferred: {}",e.getClass().getSimpleName());}
    }

    void cleanupFaceOne() {
        var tasks=jdbc.queryForList("SELECT account_id,profile_id FROM ai_face_profile_cleanup WHERE state='pending' ORDER BY created_at LIMIT 1");
        if(tasks.isEmpty())return;
        var task=tasks.get(0);Long account=((Number)task.get("account_id")).longValue();String profile=(String)task.get("profile_id");
        try {
            faces.cleanupForAccount(account,profile);
            jdbc.update("DELETE FROM ai_face_profile_cleanup WHERE account_id=? AND profile_id=?",account,profile);
        }catch(Exception e){log.warn("face cleanup deferred: {}",e.getClass().getSimpleName());}
    }
}
