package xiaozhi.modules.personmemory;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.*;
import java.util.*;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.jdbc.core.RowCallbackHandler;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.useridentity.service.AccountIdentityStateService;

/** Behavioral facts have original voice ownership and a per-person analysis watermark. */
@Service
@RequiredArgsConstructor
public class PersonBehaviorService {
    private final JdbcTemplate jdbc;
    private final ObjectMapper json;
    private final PersonMemoryService memory;
    private final AccountIdentityStateService identities;

    @Transactional
    public void record(PersonTurnDTO actor,String event,String content) {
        identities.lock(actor.getAccountId()); memory.validateActor(actor,false,true);
        try {
            Map<String,Object> row=json.readValue(content,new TypeReference<>(){});
            long sequence=Long.parseLong(Objects.toString(row.get("seq"),"0"));
            long generation=Long.parseLong(Objects.toString(row.get("generation"),"-1"));
            long timestamp=((Number)row.get("ts")).longValue();
            String raw=Objects.toString(row.get("raw"),""),intent=Objects.toString(row.get("intent"),""),outcome=Objects.toString(row.get("outcome"),"");
            if(sequence<=0 || generation!=actor.getGeneration() || !actor.getPersonId().equals(row.get("person")) ||
                !actor.getTurnId().equals(row.get("turn")) || !event.equals(row.get("event")) || event.length()>128 ||
                timestamp<Instant.now().minus(Duration.ofDays(30)).getEpochSecond() || timestamp>Instant.now().plusSeconds(60).getEpochSecond() ||
                raw.length()>2048 || intent.length()>64 || !Set.of("conversation","executed","failed").contains(outcome)) throw new RenException("行为归属或格式无效");
            Integer existing=jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_behavior_event WHERE account_id=? AND user_id=? AND generation=? AND event_id=?",Integer.class,actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),"server-turn:"+actor.getTurnId());
            if(existing!=null && existing>0)return;
            jdbc.update("INSERT IGNORE INTO ai_person_behavior_event(account_id,user_id,generation,device_id,event_id,sequence_no,turn_id,occurred_at,intent,outcome,raw_text) VALUES(?,?,?,?,?,?,?,?,?,?,?)",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getDeviceId(),event,sequence,actor.getTurnId(),timestamp,intent,outcome,raw);
        } catch(RenException e){throw e;} catch(Exception e){throw new RenException("行为材料格式无效");}
    }

    @Transactional
    public Map<String,Object> prepare(PersonTurnDTO actor) {
        identities.lock(actor.getAccountId());memory.validateActor(actor,false);
        memory.captureBehavior(actor);
        jdbc.update("INSERT IGNORE INTO ai_person_behavior_analysis(account_id,user_id,generation) VALUES(?,?,?)",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        Map<String,Object> state=jdbc.queryForMap("SELECT *,lease_until>NOW() AS busy,last_completed_at>DATE_SUB(NOW(),INTERVAL 7 DAY) AS recent FROM ai_person_behavior_analysis WHERE account_id=? AND user_id=? AND generation=? FOR UPDATE",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        if(Boolean.TRUE.equals(state.get("busy")) || number(state.get("busy"))==1)return Map.of("status","busy");
        long after=number(state.get("processed_watermark"));
        var sizes=jdbc.queryForMap("SELECT COALESCE(MAX(id),0) AS watermark,COALESCE(SUM(OCTET_LENGTH(raw_text)),0) AS bytes FROM ai_person_behavior_event WHERE account_id=? AND user_id=? AND generation=? AND id>?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),after);
        long watermark=number(sizes.get("watermark"));
        if(watermark<=after || (number(state.get("recent"))==1 && number(sizes.get("bytes"))<16000))return Map.of("status","no_new_analysis");
        String job=AccountIdentityStateService.newId();
        jdbc.update("UPDATE ai_person_behavior_analysis SET job_id=?,job_watermark=?,lease_until=DATE_ADD(NOW(),INTERVAL 10 MINUTE) WHERE account_id=? AND user_id=? AND generation=?",job,watermark,actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        SummaryAccumulator summary=new SummaryAccumulator();
        // Stream all rows: retaining only three samples per day/hour keeps
        // memory bounded without silently losing heavy users' activity.
        jdbc.query("SELECT occurred_at,raw_text,outcome,intent FROM ai_person_behavior_event WHERE account_id=? AND user_id=? AND generation=? AND id<=? AND occurred_at>=? ORDER BY id",(RowCallbackHandler) row->summary.add(Map.of("occurred_at",row.getLong("occurred_at"),"raw_text",row.getString("raw_text"),"outcome",row.getString("outcome"),"intent",row.getString("intent"))),actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),watermark,Instant.now().minus(Duration.ofDays(7)).getEpochSecond());
        return Map.of("status","ready","server_job",job,"person_id",actor.getPersonId(),"watermark",Long.toString(watermark),"summaries",summary.result());
    }

    static List<Map<String,Object>> summarize(List<Map<String,Object>> rows) {
        SummaryAccumulator result=new SummaryAccumulator();rows.forEach(result::add);return result.result();
    }
    static class SummaryAccumulator {
        static class Day {int count;final List<Map<String,Object>> samples=new ArrayList<>();}
        final Map<Integer,Map<LocalDate,Day>> hours=new TreeMap<>();
        void add(Map<String,Object> row) {
            var time=Instant.ofEpochSecond(number(row.get("occurred_at"))).atZone(ZoneId.of("Asia/Shanghai"));
            Day day=hours.computeIfAbsent(time.getHour(),ignored->new TreeMap<>()).computeIfAbsent(time.toLocalDate(),ignored->new Day());
            day.count++;day.samples.add(row);
            day.samples.sort(Comparator.comparingInt((Map<String,Object> item)->Objects.toString(item.get("raw_text"),"").length()).reversed());
            if(day.samples.size()>3)day.samples.remove(3);
        }
        List<Map<String,Object>> result() {
        List<Map<String,Object>> result=new ArrayList<>();
        hours.forEach((hour,days)->{
            int count=days.values().stream().mapToInt(day->day.count).sum();
            // Weak/rare activity remains data; the secondary model must not invent a habit.
            if(days.size()<5 || count<10)return;
            List<Map<String,Object>> samples=new ArrayList<>();
            days.forEach((date,day)->samples.add(Map.of("date",date.toString(),"events",day.samples)));
            result.add(Map.of("hour",hour,"days_active",days.size(),"total_count",count,"samples",samples));
        });
        return result;
        }
    }

    @Transactional
    public Map<String,Object> complete(PersonTurnDTO actor,String job,String content) {
        identities.lock(actor.getAccountId());memory.validateActor(actor,false);
        var state=jdbc.queryForMap("SELECT * FROM ai_person_behavior_analysis WHERE account_id=? AND user_id=? AND generation=? FOR UPDATE",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        if(!Objects.equals(job,state.get("job_id")))throw new RenException("行为分析任务已变更");
        long watermark=number(state.get("job_watermark"));
        memory.material(actor,job,"habit_analysis",content);
        jdbc.update("UPDATE ai_person_behavior_analysis SET processed_watermark=GREATEST(processed_watermark,?),lease_until=NULL,last_completed_at=NOW() WHERE account_id=? AND user_id=? AND generation=?",watermark,actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        jdbc.update("INSERT INTO ai_person_behavior_watermark(account_id,user_id,generation,device_id,sequence_no) SELECT account_id,user_id,generation,device_id,MAX(sequence_no) FROM ai_person_behavior_event WHERE account_id=? AND user_id=? AND generation=? AND id<=? GROUP BY account_id,user_id,generation,device_id ON DUPLICATE KEY UPDATE sequence_no=GREATEST(sequence_no,VALUES(sequence_no))",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),watermark);
        return acknowledgements(actor);
    }

    @Transactional
    public Map<String,Object> acknowledgements(PersonTurnDTO actor) {
        memory.validateActor(actor,false);
        var devices=jdbc.queryForList("SELECT device_id,CAST(sequence_no AS CHAR) AS watermark FROM ai_person_behavior_watermark WHERE account_id=? AND user_id=? AND generation=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        return Map.of("device_watermarks",devices);
    }
    @Scheduled(cron="0 20 3 * * *",zone="Asia/Shanghai")
    public void pruneProcessed() {
        // Durable device watermarks survive deletion of processed raw material.
        jdbc.update("DELETE e FROM ai_person_behavior_event e JOIN ai_person_behavior_analysis a ON a.account_id=e.account_id AND a.user_id=e.user_id AND a.generation=e.generation WHERE e.id<=a.processed_watermark AND e.occurred_at<?",Instant.now().minus(Duration.ofDays(30)).getEpochSecond());
    }
    private static long number(Object value){return value instanceof Number n?n.longValue():Boolean.TRUE.equals(value)?1:0;}
}
