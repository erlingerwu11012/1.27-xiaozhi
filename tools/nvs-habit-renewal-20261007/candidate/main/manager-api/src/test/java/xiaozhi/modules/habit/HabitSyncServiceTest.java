package xiaozhi.modules.habit;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;
import xiaozhi.modules.habit.dto.HabitDTO;
import xiaozhi.modules.habit.service.HabitSyncService;
import xiaozhi.modules.useridentity.service.AccountIdentityStateService;

public class HabitSyncServiceTest {
    JdbcTemplate jdbc=mock(JdbcTemplate.class);
    HabitSyncService service=new HabitSyncService(jdbc,mock(AccountIdentityStateService.class));
    HabitDTO dto(){HabitDTO d=new HabitDTO();d.setDeviceId("dev");d.setRecipientPersonId("usr_abc");d.setDescription("喝水");d.setHour(8);return d;}
    Map<String,Object> row(){Map<String,Object> r=new HashMap<>();r.put("id",9);r.put("user_id",42L);r.put("device_id","dev");r.put("recipient_person_id","usr_abc");r.put("recipient_display_name","张");r.put("intent","drink");r.put("description","喝水");r.put("hour",8);r.put("minute",0);r.put("advance_minutes",2);r.put("enabled",true);r.put("config_version",1L);return r;}
    void owned(){when(jdbc.queryForObject("SELECT COUNT(*) FROM ai_device WHERE user_id=? AND mac_address=?",Integer.class,42L,"dev")).thenReturn(1);when(jdbc.queryForObject("SELECT COUNT(*) FROM ai_user_identity WHERE account_id=? AND user_id=? AND status='active'",Integer.class,42L,"usr_abc")).thenReturn(1);}
    @Test void rejectsForeignDevice(){when(jdbc.queryForObject(anyString(),eq(Integer.class),eq(42L),eq("dev"))).thenReturn(0);assertThrows(RuntimeException.class,()->service.validateBinding(42L,dto()));}
    @Test void rejectsForeignRecipient(){owned();when(jdbc.queryForList(anyString(),eq(String.class),eq(42L),eq("usr_abc"))).thenReturn(List.of());assertThrows(RuntimeException.class,()->service.validateBinding(42L,dto()));}
    @Test void publicRecipientNeedsOwnedDevice(){owned();HabitDTO d=dto();d.setRecipientPersonId("all");assertEquals("公共接收人",service.validateBinding(42L,d));}
    @Test void missingAccountIsNotInferred(){when(jdbc.queryForList("SELECT * FROM sys_habits WHERE id=? FOR UPDATE",9)).thenReturn(List.of(new HashMap<>()));assertEquals("needs_binding",service.record(9).get("error"));}
    @Test void hashIncludesDesiredEnabledState(){owned();Map<String,Object> r=row();when(jdbc.queryForList("SELECT * FROM sys_habits WHERE id=? FOR UPDATE",9)).thenReturn(List.of(r));Map<?,?> p=(Map<?,?>)service.record(9).get("payload");assertEquals(true,p.get("enabled"));assertEquals(64,p.get("content_hash").toString().length());String old=p.get("content_hash").toString();r.put("enabled",0);Map<?,?> next=(Map<?,?>)service.record(9).get("payload");assertNotEquals(old,next.get("content_hash"));}
    @Test void wrongHashCannotMarkSynced(){owned();when(jdbc.queryForList("SELECT * FROM sys_habits WHERE id=? FOR UPDATE",9)).thenReturn(List.of(row()));assertFalse(service.acknowledge(new HabitSyncService.Ack(9,"x",1L,"synced",null,5)));verify(jdbc,never()).update(startsWith("UPDATE sys_habits SET synced=?"),any(Object[].class));}
    @Test void staleVersionCannotMarkSynced(){owned();when(jdbc.queryForList("SELECT * FROM sys_habits WHERE id=? FOR UPDATE",9)).thenReturn(List.of(row()));Map<?,?> p=(Map<?,?>)service.record(9).get("payload");assertFalse(service.acknowledge(new HabitSyncService.Ack(9,p.get("content_hash").toString(),2L,"synced",null,5)));}
    @Test void savedReceiptAccepted(){owned();when(jdbc.queryForList("SELECT * FROM sys_habits WHERE id=? FOR UPDATE",9)).thenReturn(List.of(row()));Map<?,?> p=(Map<?,?>)service.record(9).get("payload");assertTrue(service.acknowledge(new HabitSyncService.Ack(9,p.get("content_hash").toString(),1L,"synced",null,5)));}
    @Test void legacyBindingPersistsChosenDevice(){
        owned();when(jdbc.queryForList(anyString(),eq(String.class),eq(42L),eq("usr_abc"))).thenReturn(List.of("张"));
        Map<String,Object> r=row();r.put("device_id","default");r.put("sync_state","needs_binding");
        when(jdbc.queryForList("SELECT * FROM sys_habits WHERE id=? FOR UPDATE",9)).thenReturn(List.of(r));service.update(42L,9,dto());
        org.mockito.ArgumentCaptor<Object[]> args=org.mockito.ArgumentCaptor.forClass(Object[].class);
        verify(jdbc).update(startsWith("UPDATE sys_habits SET description=?"),args.capture());assertEquals("dev",args.getValue()[5]);
    }
    @Test void verifiedRuleCannotMoveWithoutStoppingOriginal(){
        owned();when(jdbc.queryForList(anyString(),eq(String.class),eq(42L),eq("usr_abc"))).thenReturn(List.of("张"));
        Map<String,Object> r=row();r.put("device_id","old_dev");r.put("sync_state","synced");r.put("device_rule_id",5);
        when(jdbc.queryForList("SELECT * FROM sys_habits WHERE id=? FOR UPDATE",9)).thenReturn(List.of(r));assertThrows(RuntimeException.class,()->service.update(42L,9,dto()));
    }
    @Test void enabledRuleNeedsPositiveDeviceId(){owned();when(jdbc.queryForList("SELECT * FROM sys_habits WHERE id=? FOR UPDATE",9)).thenReturn(List.of(row()));Map<?,?> p=(Map<?,?>)service.record(9).get("payload");assertThrows(RuntimeException.class,()->service.acknowledge(new HabitSyncService.Ack(9,p.get("content_hash").toString(),1L,"synced",null,0)));}
}
