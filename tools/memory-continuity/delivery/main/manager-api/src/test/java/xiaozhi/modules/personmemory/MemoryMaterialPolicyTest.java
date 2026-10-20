package xiaozhi.modules.personmemory;
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
  assertTrue(messages.get(0).get("content").contains("\"role\":\"assistant\""));
 }
 @Test void unansweredQuestionAndAssistantGuessAreNotReliableUserFacts() {
  assertFalse(RecentArchiveService.factualUser("我的台灯叫什么？"));
  assertFalse(RecentArchiveService.factualUser("告诉我昨天喜欢什么"));
  assertTrue(RecentArchiveService.factualUser("我的测试台灯叫银杏灯，放在书桌左侧。"));
 }
}
