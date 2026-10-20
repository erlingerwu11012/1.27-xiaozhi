package xiaozhi.modules.personmemory;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import com.fasterxml.jackson.databind.ObjectMapper;
import xiaozhi.modules.useridentity.service.AccountIdentityStateService;

@EnabledIfEnvironmentVariable(named="PERSON_MEMORY_TEST_DATABASE",matches="bailian_memory_test_[a-zA-Z0-9_]+")
class PersonMemoryDatabaseTest {
    JdbcTemplate jdbc;TransactionTemplate transaction;
    AccountIdentityStateService identities;PersonMemoryService memory;PersonBehaviorService behaviors;MemoryGatewayClient gateway;
    @BeforeEach void setup() {
        String database=System.getenv("PERSON_MEMORY_TEST_DATABASE");
        assertTrue(database.startsWith("bailian_memory_test_"));
        var source=new DriverManagerDataSource("jdbc:mysql://127.0.0.1:3306/"+database+"?useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai","root",System.getenv("PERSON_MEMORY_TEST_PASSWORD"));
        jdbc=new JdbcTemplate(source);transaction=new TransactionTemplate(new DataSourceTransactionManager(source));
        identities=new AccountIdentityStateService(jdbc);
        gateway=mock(MemoryGatewayClient.class);
        when(gateway.cloudUserId(anyLong(),anyString(),anyLong())).thenAnswer(i->"synthetic_"+i.getArgument(0)+"_"+i.getArgument(1)+"_"+i.getArgument(2));
        memory=new PersonMemoryService(jdbc,identities,gateway,new ObjectMapper());
        ReflectionTestUtils.setField(memory,"enabled",true);ReflectionTestUtils.setField(memory,"maxChars",16000);
        behaviors=new PersonBehaviorService(jdbc,new ObjectMapper(),memory,identities);
        for(String table:List.of("ai_identity_cleanup_device","ai_identity_cleanup","ai_person_behavior_event","ai_person_behavior_analysis","ai_person_behavior_watermark","ai_person_material","ai_memory_task","ai_memory_override","ai_person_memory_entity","ai_device_identity_capability","ai_agent_voice_print","ai_user_identity","ai_account_identity_state","ai_device","ai_agent"))jdbc.update("DELETE FROM "+table);
        jdbc.update("INSERT INTO ai_agent(id,user_id,mem_model_id) VALUES('agent_test',99001,'Memory_bailian'),('agent_other',99002,'Memory_mem_local_short')");
        jdbc.update("INSERT INTO ai_device(id,user_id,mac_address,agent_id) VALUES('device_test',99001,'test-device-a','agent_test'),('device_other',99002,'test-device-b','agent_other')");
    }
    PersonTurnDTO actor(Map<String,Object> state,String person,String status,long generation) {
        PersonTurnDTO actor=new PersonTurnDTO();actor.setAccountId(99001L);actor.setDeviceId("test-device-a");actor.setAgentId("agent_test");actor.setTurnId(UUID.randomUUID().toString());
        actor.setPersonId(person);actor.setStatus(status);actor.setGeneration(generation);actor.setDirectoryVersion(((Number)state.get("directory_version")).longValue());
        actor.setVoiceprintId("voice_test");actor.setTemplateVersion(1);return actor;
    }
    @Test void firstBindWaitsForCapabilitiesThenRetiresDefaultAndNeverResurrects() {
        transaction.executeWithoutResult(tx->{
            var state=identities.snapshot(99001L);String old=(String)state.get("default_user_id");
            var initial=actor(state,old,"default",1);memory.material(initial,"test-message","dialogue","旧默认记录");
            jdbc.update("INSERT INTO ai_user_identity(account_id,user_id,display_name,kind) VALUES(99001,'usr_member_test','爸爸','member')");
            jdbc.update("INSERT INTO ai_agent_voice_print(id,agent_id,source_name,audio_id,user_id,creator,vector_id) VALUES('voice_test','agent_test','爸爸','audio_test','usr_member_test',99001,'vector_test')");
            assertEquals("transition_pending",identities.snapshot(99001L).get("mode"));
            assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM ai_user_identity WHERE user_id=?",Integer.class,old));
            identities.reportCapability(99001L,"test-device-a",Map.of("identityCleanup",2,"personalIdentity",2),"synthetic-v2");
            var personal=identities.snapshot(99001L);assertEquals("personal",personal.get("mode"));
            assertNull(personal.get("default_user_id"));
            assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_material",Integer.class));
            assertThrows(RuntimeException.class,()->memory.material(initial,"late-message","dialogue","不能复活"));
            String cleanup=jdbc.queryForObject("SELECT id FROM ai_identity_cleanup WHERE user_id=?",String.class,old);
            identities.acknowledgeCleanup(99001L,"test-device-a",cleanup);
            assertEquals(1,jdbc.queryForObject("SELECT local_done FROM ai_identity_cleanup WHERE id=?",Integer.class,cleanup));
            identities.deleteMember(99001L,"usr_member_test");
            var next=identities.snapshot(99001L);assertEquals("default",next.get("mode"));assertNotEquals(old,next.get("default_user_id"));assertEquals(2L,((Number)next.get("default_generation")).longValue());
            // A repeated old device acknowledgement does not delete the new default.
            identities.acknowledgeCleanup(99001L,"test-device-a",cleanup);
            assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM ai_user_identity WHERE user_id=?",Integer.class,next.get("default_user_id")));
        });
    }
    @Test void foreignDeviceAndUnknownActorCannotStoreBehavior() {
        transaction.executeWithoutResult(tx->{
            var state=identities.snapshot(99001L);var actor=actor(state,(String)state.get("default_user_id"),"unknown",1);
            assertThrows(RuntimeException.class,()->behaviors.record(actor,"bad","{}"));
            actor.setStatus("default");actor.setDeviceId("test-device-b");
            assertThrows(RuntimeException.class,()->memory.material(actor,"foreign","dialogue","串账号"));
            assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_material",Integer.class));
        });
    }
    void behavior(PersonTurnDTO actor,String event,long sequence,long timestamp) {
        try {
            behaviors.record(actor,event,new ObjectMapper().writeValueAsString(Map.of("seq",sequence,"generation",actor.getGeneration(),"person",actor.getPersonId(),"turn",actor.getTurnId(),"event",event,"ts",timestamp,"intent","music.play","outcome","executed","raw","每天早上播放音乐")));
        }catch(java.io.IOException error){throw new AssertionError(error);}
    }
    @Test void defaultCorrectionStaysLocalAndNeverCreatesCloudMaterial() {
        transaction.executeWithoutResult(tx->{
            var state=identities.snapshot(99001L);var actor=actor(state,(String)state.get("default_user_id"),"default",1);
            memory.material(actor,"initial","dialogue","我喜欢咖啡");memory.override(actor,"correct","咖啡","我现在喜欢茶");
            assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_material",Integer.class));
            assertEquals("local_only",jdbc.queryForObject("SELECT state FROM ai_memory_override",String.class));
            verifyNoInteractions(gateway);
        });
    }
    @Test void behaviorAnalysisPreservesPeopleNewRowsAndOfflineWatermarks() {
        transaction.executeWithoutResult(tx->{
            identities.snapshot(99001L);
            jdbc.update("INSERT INTO ai_device(id,user_id,mac_address,agent_id) VALUES('device_second',99001,'test-device-second','agent_test')");
            for(String device:List.of("test-device-a","test-device-second"))identities.reportCapability(99001L,device,Map.of("identityCleanup",2,"personalIdentity",2),"synthetic-v2");
            jdbc.update("INSERT INTO ai_user_identity(account_id,user_id,display_name,kind) VALUES(99001,'usr_a','爸爸','member'),(99001,'usr_b','孩子','member')");
            jdbc.update("INSERT INTO ai_agent_voice_print(id,agent_id,source_name,audio_id,user_id,creator,vector_id) VALUES('voice_test','agent_test','爸爸','audio_a','usr_a',99001,'vector_a'),('voice_b','agent_test','孩子','audio_b','usr_b',99001,'vector_b')");
            var state=identities.snapshot(99001L);var a=actor(state,"usr_a","matched",0);var b=actor(state,"usr_b","matched",0);b.setVoiceprintId("voice_b");
            for(int index=1;index<=10;index++) {
                long at=java.time.LocalDate.now(java.time.ZoneId.of("Asia/Shanghai")).minusDays((index+1)/2).atTime(8,0).atZone(java.time.ZoneId.of("Asia/Shanghai")).toEpochSecond();
                behavior(a,"a-"+index,index,at);behavior(a,"a-"+index,index,at);behavior(b,"b-"+index,index,at);
            }
            assertEquals(20,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_behavior_event",Integer.class));
            var second=actor(state,"usr_a","matched",0);second.setDeviceId("test-device-second");behavior(second,"second-1",1,java.time.Instant.now().minusSeconds(5).getEpochSecond());
            var job=behaviors.prepare(a);assertEquals("ready",job.get("status"));assertEquals(1,((List<?>)job.get("summaries")).size());
            behavior(a,"after-prepare",11,java.time.Instant.now().minusSeconds(4).getEpochSecond());
            var acknowledged=behaviors.complete(a,(String)job.get("server_job"),"根据已执行结果完成分析");
            var watermarks=(List<Map<String,Object>>)acknowledged.get("device_watermarks");
            assertTrue(watermarks.stream().anyMatch(row->row.get("device_id").equals("test-device-a") && row.get("watermark").equals("10")));
            assertTrue(watermarks.stream().anyMatch(row->row.get("device_id").equals("test-device-second") && row.get("watermark").equals("1")));
            assertEquals(0,((List<?>)behaviors.acknowledgements(b).get("device_watermarks")).size());
            var other=behaviors.prepare(b);assertThrows(RuntimeException.class,()->behaviors.complete(b,(String)other.get("server_job"),"x".repeat(65537)));
            assertEquals(0L,jdbc.queryForObject("SELECT processed_watermark FROM ai_person_behavior_analysis WHERE user_id='usr_b'",Long.class));
            jdbc.update("UPDATE ai_person_behavior_event SET occurred_at=1 WHERE user_id='usr_a' AND event_id<>'after-prepare'");
            behaviors.pruneProcessed();
            assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_behavior_event WHERE user_id='usr_a'",Integer.class));
            assertEquals(10,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_behavior_event WHERE user_id='usr_b'",Integer.class));
            assertEquals(watermarks,behaviors.acknowledgements(a).get("device_watermarks"));
        });
    }
}
