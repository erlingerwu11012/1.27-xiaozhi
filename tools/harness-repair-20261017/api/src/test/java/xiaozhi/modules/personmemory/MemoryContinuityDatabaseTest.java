package xiaozhi.modules.personmemory;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.test.util.ReflectionTestUtils;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.*;
@EnabledIfEnvironmentVariable(named="PERSON_MEMORY_TEST_DATABASE",matches="bailian_memory_test_[a-zA-Z0-9_]+")
class MemoryContinuityDatabaseTest extends PersonMemoryDatabaseTest {
 @BeforeEach void archives(){jdbc.update("DELETE FROM ai_agent_chat_history");jdbc.update("DELETE FROM ai_agent_chat_audio");jdbc.update("DELETE FROM ai_archive_retired_event");}
 PersonTurnDTO member(){
  identities.snapshot(99001L);identities.reportCapability(99001L,"test-device-a",Map.of("identityCleanup",2,"personalIdentity",2),"synthetic-v2");
  jdbc.update("INSERT INTO ai_user_identity(account_id,user_id,display_name,kind) VALUES(99001,'usr_member','爸爸','member')");
  jdbc.update("INSERT INTO ai_agent_voice_print(id,agent_id,source_name,audio_id,user_id,creator,vector_id) VALUES('voice_test','agent_test','爸爸','audio_test','usr_member',99001,'vector_test')");
  var a=actor(identities.snapshot(99001L),"usr_member","matched",0);a.setCapturedAt(System.currentTimeMillis());return a;
 }
 MemoryDailyWorker worker(){return new MemoryDailyWorker(jdbc,new ObjectMapper(),transaction,gateway,memory,mock(xiaozhi.modules.face.service.FaceProxyService.class));}
 void mark(){jdbc.update("UPDATE ai_person_memory_entity SET daily_watermark=(SELECT MAX(id) FROM ai_person_material)");}
 @Test void boundaryIncludesOnlyMaterialsBeforeLatestBeijing0300(){transaction.executeWithoutResult(tx->{
  var a=member();memory.material(a,"before-boundary","dialogue","窗口前原文");
  long first=jdbc.queryForObject("SELECT MAX(id) FROM ai_person_material",Long.class);
  var now=java.time.ZonedDateTime.now(java.time.ZoneId.of("Asia/Shanghai"));var day=now.getHour()<3?now.toLocalDate().minusDays(1):now.toLocalDate();long boundary=day.atTime(3,0).atZone(now.getZone()).toEpochSecond();
  jdbc.update("UPDATE ai_person_material SET created_at=FROM_UNIXTIME(?) WHERE id=?",boundary-1,first);
  memory.material(a,"at-boundary","dialogue_assistant","新窗口原文");long next=jdbc.queryForObject("SELECT MAX(id) FROM ai_person_material",Long.class);
  jdbc.update("UPDATE ai_person_material SET created_at=FROM_UNIXTIME(?) WHERE id=?",boundary,next);
  var w=worker();try{w.captureDailyBoundary();assertEquals(first,jdbc.queryForObject("SELECT daily_watermark FROM ai_person_memory_entity",Long.class));w.captureDailyBoundary();assertEquals(first,jdbc.queryForObject("SELECT daily_watermark FROM ai_person_memory_entity",Long.class));assertEquals(2,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_material",Integer.class));}finally{w.close();}
 });}
 @Test void thresholdCarriesAcrossDaysAndSuccessOnlyDeletesProcessedQueue(){transaction.executeWithoutResult(tx->{
  var a=member();memory.material(a,"u","dialogue","a".repeat(39999));memory.material(a,"reply","dialogue_assistant","我的测试台灯叫银杏灯");memory.material(a,"end","dialogue_end","completed");
  var w=worker();try{mark();w.buildBatch(jdbc.queryForMap("SELECT * FROM ai_person_memory_entity"));assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM ai_memory_task",Integer.class));
   // Second day carries forward the first day's source; no arbitrary daily reset.
   a.setTurnId("second");memory.material(a,"u2","dialogue","abcd");memory.material(a,"end2","dialogue_end","completed");mark();w.buildBatch(jdbc.queryForMap("SELECT * FROM ai_person_memory_entity"));
   assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM ai_memory_task",Integer.class));
   var task=jdbc.queryForMap("SELECT * FROM ai_memory_task");assertTrue(task.get("payload").toString().contains("银杏灯"));
   memory.material(a,"later","dialogue","新材料保留");w.complete(task);assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_material",Integer.class));
  }finally{w.close();}
 });}
 @Test void unfinishedTurnNeverAdvancesWatermark(){transaction.executeWithoutResult(tx->{var a=member();memory.material(a,"u","dialogue","a".repeat(40000));mark();var w=worker();try{w.buildBatch(jdbc.queryForMap("SELECT * FROM ai_person_memory_entity"));assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM ai_memory_task",Integer.class));}finally{w.close();}});}
 void history(PersonTurnDTO a,String turn,int type,String content,String audio,long time){jdbc.update("INSERT INTO ai_agent_chat_history(mac_address,agent_id,session_id,chat_type,content,audio_id,account_id,person_id,identity_status,turn_id,event_id,directory_version,default_generation,recall_allowed,created_at) VALUES('test-device-a','agent_test','session',?,?,?,?,?,'matched',?,?,?,0,TRUE,FROM_UNIXTIME(?))",type,content,audio,a.getAccountId(),a.getPersonId(),turn,turn+":"+type,a.getDirectoryVersion(),time);}
 @Test void retentionKeeps50TurnsAnd72hAudioWithoutDeletingPending(){transaction.executeWithoutResult(tx->{var a=member();long now=System.currentTimeMillis()/1000;
  for(int i=0;i<51;i++){String clip="clip"+i;jdbc.update("INSERT INTO ai_agent_chat_audio(id,audio) VALUES(?,?)",clip,new byte[]{1,2});history(a,"turn"+i,1,"我的测试台灯叫银杏灯",clip,now+i);history(a,"turn"+i,2,"已记录",null,now+i);}
  jdbc.update("INSERT INTO ai_agent_chat_audio(id,audio) VALUES('expired',?)",new byte[]{3});history(a,"old",1,"旧文本","expired",now-72*3600-1);
  memory.material(a,"pending","dialogue","跨日原文必须保留");var clean=new ArchiveRetentionWorker(jdbc,transaction,identities);clean.clean();
  assertEquals(50,jdbc.queryForObject("SELECT COUNT(DISTINCT turn_id) FROM ai_agent_chat_history WHERE content<>''",Integer.class));
  assertEquals(50,jdbc.queryForObject("SELECT COUNT(*) FROM ai_agent_chat_audio",Integer.class));
  assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_material",Integer.class));
  var recent=new RecentArchiveService(jdbc,memory,identities);assertEquals(50,((Number)recent.continuation(a).get("turns")).intValue());
  assertTrue(recent.duplicate(99001L,"old:1"));
 });}
 @Test void crossDayPendingIsLocallySearchableAndScoped(){transaction.executeWithoutResult(tx->{var a=member();memory.material(a,"pending","dialogue","我的测试台灯叫银杏灯，放在书桌左侧。");jdbc.update("UPDATE ai_person_material SET created_at=DATE_SUB(NOW(),INTERVAL 3 DAY)");
  var recent=new RecentArchiveService(jdbc,memory,identities);assertEquals(false,recent.search(a,"我的测试台灯叫什么").get("reliable"));a.setTurnId("cross-day-query");var result=recent.search(a,"我的测试台灯叫什么");assertEquals(true,result.get("reliable"));assertTrue(result.get("text").toString().contains("银杏灯"));
  a.setAgentId("agent_other");assertThrows(RuntimeException.class,()->recent.search(a,"测试台灯"));
 });}

 @Test void explicitFactSaveReadbackAndIdempotency(){transaction.executeWithoutResult(tx->{
  var a=member();
  var saved=memory.add(a,"我最爱喝咖啡");
  assertEquals(true,saved.get("local_applied"));
  assertNotNull(saved.get("record_id"));
  var again=memory.add(a,"我最爱喝咖啡");
  assertEquals(saved.get("record_id"),again.get("record_id"));
  var archive=new RecentArchiveService(jdbc,memory,identities);
  var read=archive.search(a,"我最爱喝什么","related",1,List.of(saved.get("record_id").toString()));
  var items=(List<Map<String,Object>>)read.get("items");
  assertEquals(1,items.size());assertEquals("我最爱喝咖啡",items.get(0).get("text"));
  assertEquals(saved.get("record_id"),items.get(0).get("record_id"));
  assertThrows(xiaozhi.common.exception.RenException.class,()->memory.add(a,"我最爱喝绿茶"));
 });}
 @Test void explicitFactRejectsQuestionsAndStaleIdentity(){transaction.executeWithoutResult(tx->{
  var a=member();
  assertThrows(xiaozhi.common.exception.RenException.class,()->memory.add(a,"我最爱喝什么？"));
  assertThrows(xiaozhi.common.exception.RenException.class,()->memory.add(a,"请你记住我最爱喝咖啡"));
  a.setDirectoryVersion(a.getDirectoryVersion()+1);
  assertThrows(xiaozhi.common.exception.RenException.class,()->memory.add(a,"我最爱喝咖啡"));
 });}
}
