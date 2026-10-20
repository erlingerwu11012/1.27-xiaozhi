package xiaozhi.modules.personmemory;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import com.fasterxml.jackson.databind.ObjectMapper;
@EnabledIfEnvironmentVariable(named="PERSON_MEMORY_TEST_DATABASE",matches="bailian_memory_test_[a-zA-Z0-9_]+")
class QuietMaintenanceDatabaseTest extends MemoryContinuityDatabaseTest {
 @Test void attributedClosedTurnCapturedOnceWithoutDeviceSequenceCollision(){transaction.executeWithoutResult(tx->{
  var a=member();memory.material(a,"quiet-user","dialogue","我早上喝咖啡");
  assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_behavior_event",Integer.class));
  memory.material(a,"quiet-end","dialogue_end","completed");
  assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_behavior_event",Integer.class));
  assertEquals("server:test-device-a",jdbc.queryForObject("SELECT device_id FROM ai_person_behavior_event",String.class));
  memory.captureBehavior(a);memory.material(a,"quiet-end","dialogue_end","completed");
  assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_behavior_event",Integer.class));
  var job=behaviors.prepare(a);assertEquals("ready",job.get("status"));assertTrue(((List<?>)job.get("summaries")).isEmpty());
 });}
 @Test void explicitRerunUsesSameTaskAndDoesNotChangeOtherPerson(){transaction.executeWithoutResult(tx->{
  var a=member();memory.material(a,"rerun-u","dialogue","我的测试台灯叫银杏灯");memory.material(a,"rerun-end","dialogue_end","completed");
  var w=worker();try{
   assertEquals("queued_or_existing",w.rerun(a).get("status"));
   var first=jdbc.queryForMap("SELECT id,watermark FROM ai_memory_task");w.rerun(a);
   assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM ai_memory_task",Integer.class));
   assertEquals(first,jdbc.queryForMap("SELECT id,watermark FROM ai_memory_task"));
   a.setStatus("unknown");assertThrows(RuntimeException.class,()->w.rerun(a));
  }finally{w.close();}
 });}
 @Test void derivedHabitResultIsNotRepeatedAsUserMemory(){
  var rows=List.<Map<String,Object>>of(Map.of("kind","dialogue","content","我喜欢咖啡"),Map.of("kind","habit_analysis","content","自动生成的提醒推断"));
  String text=MemoryMaterialPolicy.messages(rows,new ObjectMapper()).toString();
  assertTrue(text.contains("我喜欢咖啡"));assertFalse(text.contains("自动生成的提醒推断"));
 }
 @Test void supersededCorrectionDoesNotBlockAndLegacyCompletedCorrectionIsClosed(){transaction.executeWithoutResult(tx->{
  var a=member();memory.material(a,"close-u","dialogue","我喜欢咖啡");memory.material(a,"close-end","dialogue_end","completed");
  memory.override(a,"correct","咖啡","我喜欢绿茶");
  jdbc.update("UPDATE ai_memory_override SET state='superseded'");
  memory.override(a,"correct","我喜欢绿茶","我喜欢红茶");
  jdbc.update("UPDATE ai_memory_override SET state='complete' WHERE state='pending'");
  String correction=jdbc.queryForObject("SELECT id FROM ai_memory_override WHERE state='complete'",String.class);
  jdbc.update("INSERT INTO ai_person_material(account_id,user_id,generation,agent_id,device_id,event_id,turn_id,kind,content) VALUES(99001,'usr_member',0,'agent_test','test-device-a',?,?,'dialogue','我喜欢红茶')","correction-"+correction,correction);
  var w=worker();try{
   assertEquals("queued_or_existing",w.rerun(a).get("status"));
   String payload=jdbc.queryForObject("SELECT payload FROM ai_memory_task",String.class);
   assertTrue(payload.contains("我喜欢红茶"));
   assertEquals(jdbc.queryForObject("SELECT MAX(id) FROM ai_person_material",Long.class),jdbc.queryForObject("SELECT watermark FROM ai_memory_task",Long.class));
   when(gateway.request(anyLong(),anyString(),anyLong(),anyString(),anyString(),any(),any(),any())).thenReturn(Map.of("memory_nodes",List.of()));
   memory.search(a,"我喜欢什么茶");
   verify(gateway).request(anyLong(),anyString(),anyLong(),eq("POST"),eq("memory_nodes/search"),any(),any(),any());
  }finally{w.close();}
 });}
}
