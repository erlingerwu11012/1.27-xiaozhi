package xiaozhi.modules.useridentity.service;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import xiaozhi.common.exception.RenException;

/** Account row is the serialization point for directory changes, not a JVM mutex. */
@Service
@RequiredArgsConstructor
public class AccountIdentityStateService {
    private final JdbcTemplate jdbc;

    @Transactional(propagation = Propagation.MANDATORY)
    public Map<String,Object> lock(Long accountId) {
        if (accountId == null || accountId <= 0) throw new RenException("账号无效");
        jdbc.update("INSERT IGNORE INTO ai_account_identity_state(account_id) VALUES(?)", accountId);
        Map<String,Object> state = jdbc.queryForMap(
            "SELECT * FROM ai_account_identity_state WHERE account_id=? FOR UPDATE", accountId);
        if ("default".equals(state.get("mode")) && state.get("default_user_id") == null) {
            String id = newId();
            jdbc.update("INSERT INTO ai_user_identity(account_id,user_id,display_name,status,kind,create_date) VALUES(?,?,'默认用户','active','default',NOW())", accountId,id);
            jdbc.update("UPDATE ai_account_identity_state SET default_user_id=? WHERE account_id=?", id,accountId);
            state.put("default_user_id",id);
        }
        return state;
    }

    @Transactional
    public Map<String,Object> snapshot(Long accountId) {
        lock(accountId);
        reconcile(accountId);
        Map<String,Object> state = jdbc.queryForMap("SELECT * FROM ai_account_identity_state WHERE account_id=?",accountId);
        state.put("members",jdbc.queryForList("SELECT user_id,display_name,status,kind FROM ai_user_identity WHERE account_id=? AND status='active'",accountId));
        state.put("voice_profiles",jdbc.queryForList("SELECT v.id AS voiceprint_id,v.vector_id AS speaker_id,v.user_id,u.display_name,v.template_version FROM ai_agent_voice_print v JOIN ai_user_identity u ON u.account_id=v.creator AND u.user_id=v.user_id WHERE v.creator=? AND u.status='active' AND u.kind='member' AND v.binding_state='ready' AND v.vector_id IS NOT NULL",accountId));
        if("default".equals(state.get("mode")) && !((List<?>)state.get("voice_profiles")).isEmpty())state.put("mode","transition_pending");
        state.put("cleanup_tasks",jdbc.queryForList("SELECT id,user_id,generation,directory_version FROM ai_identity_cleanup WHERE account_id=? AND state<>'complete'",accountId));
        state.put("agent_ids",jdbc.queryForList("SELECT id FROM ai_agent WHERE user_id=?",String.class,accountId));
        return state;
    }

    @Transactional(propagation = Propagation.MANDATORY)
    public void changed(Long accountId) {
        lock(accountId);
        jdbc.update("UPDATE ai_account_identity_state SET directory_version=directory_version+1 WHERE account_id=?",accountId);
        reconcile(accountId);
    }

    @Transactional(propagation = Propagation.MANDATORY)
    public void reconcile(Long accountId) {
        Map<String,Object> state=lock(accountId);
        Long count=jdbc.queryForObject("SELECT COUNT(*) FROM ai_agent_voice_print v JOIN ai_user_identity u ON u.account_id=v.creator AND u.user_id=v.user_id WHERE v.creator=? AND u.status='active' AND u.kind='member' AND v.binding_state='ready' AND v.vector_id IS NOT NULL",Long.class,accountId);
        if (count != null && count>0 && "default".equals(state.get("mode"))) {
            if(!supportsCleanup(accountId))return;
            String old=(String)state.get("default_user_id");
            long generation=((Number)state.get("default_generation")).longValue();
            long version=((Number)state.get("directory_version")).longValue()+1;
            retire(accountId,old,generation,version);
            jdbc.update("UPDATE ai_account_identity_state SET mode='personal',default_user_id=NULL,directory_version=? WHERE account_id=?",version,accountId);
        } else if ((count==null || count==0) && "personal".equals(state.get("mode"))) {
            String id=newId();
            jdbc.update("INSERT INTO ai_user_identity(account_id,user_id,display_name,status,kind,create_date) VALUES(?,?,'默认用户','active','default',NOW())",accountId,id);
            jdbc.update("UPDATE ai_account_identity_state SET mode='default',default_user_id=?,default_generation=default_generation+1,directory_version=directory_version+1 WHERE account_id=?",id,accountId);
        }
    }

    @Transactional(propagation = Propagation.MANDATORY)
    public void retire(Long accountId,String userId,long generation,long version) {
        if (userId==null || userId.isBlank()) return;
        jdbc.update("INSERT IGNORE INTO ai_identity_cleanup(id,account_id,user_id,generation,directory_version) VALUES(?,?,?,?,?)",newId(),accountId,userId,generation,version);
        jdbc.update("INSERT IGNORE INTO ai_identity_cleanup_device(cleanup_id,device_id) SELECT c.id,d.mac_address FROM ai_identity_cleanup c JOIN ai_device d ON d.user_id=c.account_id WHERE c.account_id=? AND c.user_id=? AND c.generation=?",accountId,userId,generation);
        // Suppress immediately; destructive cloud and device work is acknowledged separately.
        jdbc.update("UPDATE ai_person_memory_entity SET state='retired' WHERE account_id=? AND user_id=?",accountId,userId);
        jdbc.update("UPDATE ai_memory_task SET state='cancelled',payload=NULL WHERE account_id=? AND user_id=? AND state IN ('pending','retry')",accountId,userId);
        jdbc.update("DELETE FROM ai_person_material WHERE account_id=? AND user_id=?",accountId,userId);
        jdbc.update("DELETE FROM ai_person_behavior_event WHERE account_id=? AND user_id=?",accountId,userId);
        jdbc.update("DELETE FROM ai_person_behavior_analysis WHERE account_id=? AND user_id=?",accountId,userId);
        jdbc.update("DELETE FROM ai_person_behavior_watermark WHERE account_id=? AND user_id=?",accountId,userId);
        jdbc.update("DELETE FROM ai_memory_override WHERE account_id=? AND user_id=?",accountId,userId);
        // Voice templates have already been registered independently before retire.
        jdbc.update("DELETE a FROM ai_agent_chat_audio a JOIN ai_agent_chat_history h ON h.audio_id=a.id WHERE h.account_id=? AND h.person_id=? AND h.default_generation=?",accountId,userId,generation);
        jdbc.update("DELETE FROM ai_agent_chat_history WHERE account_id=? AND person_id=? AND default_generation=?",accountId,userId,generation);
        if(generation>0) {
            jdbc.update("UPDATE ai_agent SET summary_memory=NULL WHERE user_id=?",accountId);
            jdbc.update("INSERT IGNORE INTO ai_face_profile_cleanup(account_id,profile_id) VALUES(?,'default')",accountId);
            jdbc.update("DELETE FROM ai_user_face_binding WHERE account_id=? AND user_id=?",accountId,userId);
        }
        jdbc.update("DELETE FROM ai_user_identity WHERE account_id=? AND user_id=?",accountId,userId);
    }

    @Transactional
    public void deleteMember(Long accountId,String userId) {
        Map<String,Object> state=lock(accountId);
        List<Map<String,Object>> users=jdbc.queryForList("SELECT kind FROM ai_user_identity WHERE account_id=? AND user_id=?",accountId,userId);
        if (users.isEmpty() || !"member".equals(users.get(0).get("kind"))) throw new RenException("成员不存在");
        jdbc.update("INSERT IGNORE INTO ai_voice_vector_cleanup(vector_id,account_id) SELECT vector_id,creator FROM ai_agent_voice_print WHERE creator=? AND user_id=? AND vector_id IS NOT NULL",accountId,userId);
        jdbc.update("DELETE FROM ai_agent_voice_print WHERE creator=? AND user_id=?",accountId,userId);
        jdbc.update("INSERT IGNORE INTO ai_face_profile_cleanup(account_id,profile_id) SELECT account_id,face_profile_id FROM ai_user_face_binding WHERE account_id=? AND user_id=?",accountId,userId);
        jdbc.update("DELETE FROM ai_user_face_binding WHERE account_id=? AND user_id=?",accountId,userId);
        retire(accountId,userId,0,((Number)state.get("directory_version")).longValue()+1);
        changed(accountId);
    }

    public static String newId() { return "usr_"+UUID.randomUUID().toString().replace("-",""); }

    public boolean supportsCleanup(Long accountId) {
        Integer unsupported=jdbc.queryForObject("SELECT COUNT(*) FROM ai_device d LEFT JOIN ai_device_identity_capability c ON c.device_id=d.mac_address AND c.account_id=d.user_id WHERE d.user_id=? AND (c.cleanup_version IS NULL OR c.cleanup_version<2 OR c.identity_version<2)",Integer.class,accountId);
        return unsupported==null || unsupported==0;
    }
    public void requireCleanupCapability(Long accountId) {
        if(!supportsCleanup(accountId))throw new RenException("设备固件尚不支持个人身份清理，请升级兼容固件后再绑定声纹");
    }

    @Transactional
    public void reportCapability(Long accountId,String deviceId,Map<String,Object> versions,String firmware) {
        Integer owned=jdbc.queryForObject("SELECT COUNT(*) FROM ai_device WHERE user_id=? AND mac_address=?",Integer.class,accountId,deviceId);
        if(owned==null || owned!=1)throw new RenException("设备归属已变更");
        jdbc.update("INSERT INTO ai_device_identity_capability(device_id,account_id,identity_version,cleanup_version,behavior_version,schedule_version,firmware_version) VALUES(?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE account_id=VALUES(account_id),identity_version=VALUES(identity_version),cleanup_version=VALUES(cleanup_version),behavior_version=VALUES(behavior_version),schedule_version=VALUES(schedule_version),firmware_version=VALUES(firmware_version)",deviceId,accountId,version(versions,"personalIdentity"),version(versions,"identityCleanup"),version(versions,"personBehavior"),version(versions,"weeklySchedule"),firmware);
    }
    private int version(Map<String,Object> versions,String name){Object value=versions.get(name);return value instanceof Number number?Math.max(0,Math.min(100,number.intValue())):0;}

    @Transactional
    public void acknowledgeCleanup(Long accountId,String deviceId,String cleanupId) {
        Integer owned=jdbc.queryForObject("SELECT COUNT(*) FROM ai_device WHERE user_id=? AND mac_address=?",Integer.class,accountId,deviceId);
        if(owned==null || owned!=1)throw new RenException("设备归属已变更");
        jdbc.update("UPDATE ai_identity_cleanup_device d JOIN ai_identity_cleanup c ON c.id=d.cleanup_id SET d.confirmed_at=NOW() WHERE d.cleanup_id=? AND d.device_id=? AND c.account_id=?",cleanupId,deviceId,accountId);
        jdbc.update("UPDATE ai_identity_cleanup c SET local_done=TRUE WHERE c.account_id=? AND NOT EXISTS(SELECT 1 FROM ai_identity_cleanup_device d WHERE d.cleanup_id=c.id AND d.confirmed_at IS NULL)",accountId);
        jdbc.update("UPDATE ai_identity_cleanup SET state='complete' WHERE account_id=? AND cloud_done=TRUE AND portrait_done=TRUE AND local_done=TRUE",accountId);
    }
}
