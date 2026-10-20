package xiaozhi.modules.pay.service;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import xiaozhi.modules.pay.vo.OneApiDeviceTokenVO;
class HardwareBillingPolicyTest {
 @Test void categoriesUseOwnedTokenAndVerifiedOrigins(){
  var binding=mock(OneApiBindingService.class);var wallet=mock(HardwareWalletRechargeService.class);
  var token=new OneApiDeviceTokenVO();token.setToken("synthetic");token.setOneapiUserId(7L);
  when(binding.resolveDeviceToken(123L)).thenReturn(token);
  var policy=new HardwareBillingPolicy(binding,true,"http://127.0.0.1:3000/v1");
  ReflectionTestUtils.setField(policy,"wallet",wallet);
  for(String category:List.of("LLM","VLLM","ASR","TTS")) {
   Map<String,Object> copy=new HashMap<>(Map.of("aimi_device_gateway",true,"url","https://old.invalid"));
   policy.configure(copy,new HashMap<>(Map.of("sys_user_id",123L)),category,"summary");
   assertEquals("123",copy.get("hardware_account_id"));assertEquals("synthetic",copy.get("api_key"));assertFalse(copy.containsKey("aimi_device_gateway"));
   if(List.of("ASR","TTS").contains(category))assertTrue(copy.get("ws_url").toString().startsWith("ws://127.0.0.1:3011/bailian/"));
   else assertEquals("http://127.0.0.1:3000/v1",copy.get("base_url"));
  }
  verify(wallet,times(4)).ensureWallet(eq(123L),any());
 }
 @Test void featureOffPreservesOriginalConfiguration(){
  var binding=mock(OneApiBindingService.class);var policy=new HardwareBillingPolicy(binding,false,"http://127.0.0.1:3000/v1");
  Map<String,Object> original=new HashMap<>(Map.of("type","old"));
  policy.configure(original,Map.of("sys_user_id",123L),"LLM","llm");assertEquals(Map.of("type","old"),original);verifyNoInteractions(binding);
 }
}
