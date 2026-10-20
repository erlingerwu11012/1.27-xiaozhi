from pathlib import Path
import json
root=Path(__file__).resolve().parents[2]/'tmp/bailian-memory-product/server';mf=Path(__file__).with_name('changed.json');changed=json.loads(mf.read_text())
def write(n,t):(root/n).write_text(t,encoding='utf-8');changed.append(n)
j='main/manager-api/src/test/java/xiaozhi/modules/personmemory/'
write(j+'MemoryMaterialPolicyTest.java','''package xiaozhi.modules.personmemory;
import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;
import java.util.*;
import com.fasterxml.jackson.databind.ObjectMapper;
class MemoryMaterialPolicyTest {
 @Test void tokenBoundaryUserOnlyAndFullTranscript() {
  assertEquals(9999,MemoryMaterialPolicy.userTokens("a".repeat(39999)));
  assertEquals(10000,MemoryMaterialPolicy.userTokens("a".repeat(40000)));
  var rows=List.of(Map.<String,Object>of("kind","dialogue","content","原话"+"a".repeat(50000)),Map.<String,Object>of("kind","dialogue_assistant","content","助手猜测：喜欢紫色"));
  var messages=MemoryMaterialPolicy.messages(rows,new ObjectMapper());
  assertEquals(1,messages.size());assertTrue(messages.get(0).get("content").contains("a".repeat(50000)));
  assertTrue(messages.get(0).get("content").contains("\\\"role\\\":\\\"assistant\\\""));
 }
 @Test void unansweredQuestionAndAssistantGuessAreNotReliableUserFacts() {
  assertFalse(RecentArchiveService.factualUser("我的台灯叫什么？"));
  assertFalse(RecentArchiveService.factualUser("告诉我昨天喜欢什么"));
  assertTrue(RecentArchiveService.factualUser("我的测试台灯叫银杏灯，放在书桌左侧。"));
 }
}
''')
write(j+'MemoryContinuityDatabaseTest.java','''package xiaozhi.modules.personmemory;
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
  var recent=new RecentArchiveService(jdbc,memory,identities);var result=recent.search(a,"我的测试台灯叫什么");assertEquals(true,result.get("reliable"));assertTrue(result.get("text").toString().contains("银杏灯"));
  a.setAgentId("agent_other");assertThrows(RuntimeException.class,()->recent.search(a,"测试台灯"));
 });}
}
''')
# Replace an old regression that contradicted the already published default-local-only policy.
s=j+'PersonMemoryDatabaseTest.java';text=(root/s).read_text();start=text.index('    @Test void correctedFactRemainsOwnedAndEntersDailyExtraction()');end=text.index('    @Test void behaviorAnalysis',start)
text=text[:start]+'''    @Test void defaultCorrectionStaysLocalAndNeverCreatesCloudMaterial() {
        transaction.executeWithoutResult(tx->{
            var state=identities.snapshot(99001L);var actor=actor(state,(String)state.get("default_user_id"),"default",1);
            memory.material(actor,"initial","dialogue","我喜欢咖啡");memory.override(actor,"correct","咖啡","我现在喜欢茶");
            assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_material",Integer.class));
            assertEquals("local_only",jdbc.queryForObject("SELECT state FROM ai_memory_override",String.class));
            verifyNoInteractions(gateway);
        });
    }
'''+text[end:];write(s,text)
# Retention locking must not create default identities for dormant legacy accounts.
s='main/manager-api/src/main/java/xiaozhi/modules/personmemory/ArchiveRetentionWorker.java';text=(root/s).read_text().replace('            identities.lock(((Number)scope.get("account_id")).longValue());','            jdbc.queryForList("SELECT account_id FROM ai_account_identity_state WHERE account_id=? FOR UPDATE",scope.get("account_id"));');write(s,text)
write('main/xiaozhi-server/test/test_memory_continuity.py','''import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from core.utils.person_identity import PersonTurn
from core.utils.person_material_outbox import MaterialOutbox
from core.utils import person_short_memory as short
from core.providers.memory.bailian.bailian import MemoryProvider
from core.utils.dialogue import Dialogue,Message

def actor(agent="agent",status="matched"):
 return PersonTurn("10","dad",0,1,"personal",status,"turn","device",agent,1)
class ContinuityTest(unittest.TestCase):
 def test_agent_summary_isolation_and_person_wide_invalidation(self):
  with tempfile.TemporaryDirectory() as d,patch.object(short,"material_outbox",MaterialOutbox(str(Path(d)/"out.sqlite"))):
   a=actor();b=actor("other");dialogue=Dialogue();dialogue.compact_summary="verified compact";dialogue.source_revision=0
   short.persist_compact(a,dialogue);self.assertEqual("verified compact",short.load(a));self.assertEqual("",short.load(b))
   short.invalidate(b);self.assertEqual("",short.load(a));short.persist_compact(a,dialogue);self.assertEqual("",short.load(a))
 def test_retirement_stops_late_summary_for_every_agent(self):
  with tempfile.TemporaryDirectory() as d,patch.object(short,"material_outbox",MaterialOutbox(str(Path(d)/"out.sqlite"))):
   a=actor();dialogue=Dialogue();dialogue.compact_summary="old";dialogue.source_revision=0;short.retire("10","dad",0);short.persist_compact(a,dialogue);self.assertEqual("",short.load(a))
 def test_full_reply_chunks_and_default_is_never_uploaded(self):
  with tempfile.TemporaryDirectory() as d:
   box=MaterialOutbox(str(Path(d)/"out.sqlite"));provider=MemoryProvider({})
   with patch("core.utils.person_material_outbox.material_outbox",box):
    provider._enqueue_text(actor(),"dialogue_assistant","长"*70000,"reply")
    with box.connect() as db:rows=db.execute("SELECT content FROM material ORDER BY rowid").fetchall()
    self.assertEqual("长"*70000,"".join(r[0] for r in rows))
    provider.record_turn(SimpleNamespace(),actor(status="default"),"不会上云")
    with box.connect() as db:self.assertEqual(2,db.execute("SELECT count(*) FROM material").fetchone()[0])
if __name__=="__main__":unittest.main()
''')
mf.write_text(json.dumps(sorted(set(changed)),indent=2))
print('tests_written')
