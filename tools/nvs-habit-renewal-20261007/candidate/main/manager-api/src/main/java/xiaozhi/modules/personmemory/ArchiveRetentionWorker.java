package xiaozhi.modules.personmemory;
import java.util.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;
import xiaozhi.modules.useridentity.service.AccountIdentityStateService;

/** Independent retention: audio 72h/50, archive text 50 turns, no material deletion. */
@Slf4j @Component @RequiredArgsConstructor
public class ArchiveRetentionWorker {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transactions;
    private final AccountIdentityStateService identities;
    @Scheduled(fixedDelay=300000,initialDelay=90000)
    public void tick() {try{clean();}catch(Exception e){log.warn("archive retention deferred: {}",e.getClass().getSimpleName());}}
    public void clean() {
        long cutoff=System.currentTimeMillis()/1000-72*3600;
        var audio=jdbc.queryForList("SELECT id,audio_id FROM (SELECT h.id,h.audio_id,h.chat_type,UNIX_TIMESTAMP(h.created_at) AS stamp,ROW_NUMBER() OVER(PARTITION BY h.agent_id,h.chat_type ORDER BY h.created_at DESC,h.id DESC) AS rn FROM ai_agent_chat_history h WHERE h.audio_id IS NOT NULL) ranked WHERE chat_type<>1 OR stamp<=? OR rn>50 LIMIT 2000",cutoff);
        transactions.executeWithoutResult(tx->{for(var row:audio) {
            jdbc.update("UPDATE ai_agent_chat_history SET audio_id=NULL WHERE id=? AND audio_id=?",row.get("id"),row.get("audio_id"));
            jdbc.update("DELETE FROM ai_agent_chat_audio WHERE id=? AND NOT EXISTS(SELECT 1 FROM ai_agent_chat_history WHERE audio_id=?)",row.get("audio_id"),row.get("audio_id"));
        }});
        var scopes=jdbc.queryForList("SELECT DISTINCT COALESCE(h.account_id,a.user_id) AS account_id,h.agent_id,COALESCE(h.person_id,CONCAT('unknown:',h.mac_address)) AS person_scope,COALESCE(h.default_generation,0) AS generation FROM ai_agent_chat_history h JOIN ai_agent a ON a.id=h.agent_id WHERE h.content<>''");
        for(var scope:scopes)transactions.executeWithoutResult(tx->{
            jdbc.queryForList("SELECT account_id FROM ai_account_identity_state WHERE account_id=? FOR UPDATE",scope.get("account_id"));
            String predicate="COALESCE(account_id,(SELECT user_id FROM ai_agent WHERE id=agent_id))=? AND agent_id=? AND COALESCE(person_id,CONCAT('unknown:',mac_address))=? AND COALESCE(default_generation,0)=?";
            Object[] args={scope.get("account_id"),scope.get("agent_id"),scope.get("person_scope"),scope.get("generation")};
            var keep=jdbc.queryForList("SELECT COALESCE(NULLIF(turn_id,''),id) AS turn_key FROM ai_agent_chat_history WHERE "+predicate+" AND content<>'' GROUP BY turn_key ORDER BY MAX(created_at) DESC,MAX(id) DESC LIMIT 50",args);
            if(keep.size()<50)return;
            List<Object> values=new ArrayList<>(Arrays.asList(args));for(var row:keep)values.add(row.get("turn_key"));
            var old=jdbc.queryForList("SELECT id,audio_id,event_id FROM ai_agent_chat_history WHERE "+predicate+" AND content<>'' AND COALESCE(NULLIF(turn_id,''),id) NOT IN ("+String.join(",",Collections.nCopies(keep.size(),"?"))+") LIMIT 2000",values.toArray());
            for(var row:old) {
                if(row.get("event_id")!=null)jdbc.update("INSERT IGNORE INTO ai_archive_retired_event(account_id,event_id) VALUES(?,?)",scope.get("account_id"),row.get("event_id"));
                if(row.get("audio_id")==null)jdbc.update("DELETE FROM ai_agent_chat_history WHERE id=?",row.get("id"));
                else jdbc.update("UPDATE ai_agent_chat_history SET content='',recall_allowed=FALSE WHERE id=?",row.get("id"));
            }
        });
        // Bytes without a history reference cannot be used for enrollment or playback.
        jdbc.update("DELETE a FROM ai_agent_chat_audio a LEFT JOIN ai_agent_chat_history h ON h.audio_id=a.id WHERE h.id IS NULL");
    }
}
