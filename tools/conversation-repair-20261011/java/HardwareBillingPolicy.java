package xiaozhi.modules.pay.service;

import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import xiaozhi.modules.pay.vo.OneApiDeviceTokenVO;

/** Hardware configuration only. Aimi keeps its independent model routing. */
@Service
public class HardwareBillingPolicy {
    private final boolean enabled;
    private final String gateway;
    @Value("${hardware.billing.audio-base-url:http://127.0.0.1:3011}")
    private String audioGateway="http://127.0.0.1:3011";
    private final OneApiBindingService binding;
    @org.springframework.beans.factory.annotation.Autowired
    private HardwareWalletRechargeService wallet;
    public HardwareBillingPolicy(OneApiBindingService binding,
            @Value("${hardware.billing.enabled:false}") boolean enabled,
            @Value("${hardware.billing.gateway-base-url:http://127.0.0.1:3000/v1}") String gateway) {
        this.binding=binding; this.enabled=enabled; this.gateway=gateway;
    }
    public void configure(Map<String,Object> copy,Map<String,Object> result,String category,String operation) {
        if(!enabled||!(result.get("sys_user_id") instanceof Number)) return;
        if(!java.util.Set.of("LLM","VLLM","ASR","TTS").contains(category)) return;
        Long account=((Number)result.get("sys_user_id")).longValue();
        OneApiDeviceTokenVO token=binding.resolveDeviceToken(account);
        if(token==null||token.getToken()==null||token.getToken().isBlank())
            throw new IllegalStateException("硬件计费账户尚未就绪");
        if(wallet!=null) {
            var trusted=new xiaozhi.modules.pay.entity.SysUserOneapiBindingEntity();
            trusted.setOneapiUserId(token.getOneapiUserId());
            wallet.ensureWallet(account,trusted);
        }
        copy.remove("aimi_device_gateway");copy.remove("aimi_device_service_key");
        copy.remove("url");
        if("ASR".equals(category)||"TTS".equals(category)) {
            String audioModel="ASR".equals(category)?"qwen3-asr-flash-realtime":"qwen-audio-3.0-tts-plus";
            String root=audioGateway.replaceAll("/v1/?$", "").replaceAll("/+$", "");
            String socket=root.replaceFirst("^http:", "ws:").replaceFirst("^https:", "wss:");
            copy.put("type","ASR".equals(category)?"qwen3_asr_realtime":"qwen_audio_tts_plus");
            copy.put("model_name",audioModel);copy.put("model",audioModel);
            copy.put("ws_url",socket+("ASR".equals(category)?"/bailian/api-ws/v1/realtime":"/bailian/api-ws/v1/inference")+"?model="+audioModel);
            copy.put("api_key",token.getToken());copy.put("hardware_billing",true);
            copy.put("hardware_account_id",account.toString());
            copy.put("hardware_operation","ASR".equals(category)?"asr":"tts");
            return;
        }
        copy.put("type","openai");copy.put("model_name","VLLM".equals(category)?"qwen3-vl-plus":xiaozhi.modules.model.OfficialServiceDefaults.LLM_MODEL_NAME);
        copy.put("base_url",gateway);copy.put("api_key",token.getToken());
        copy.put("hardware_billing",true);copy.put("hardware_account_id",account.toString());
        copy.put("hardware_operation","VLLM".equals(category)?"vision":operation);
        copy.put("enable_thinking",false);
        if("LLM".equals(category)) {
            copy.put("preserve_thinking",false);
            copy.put("temperature",xiaozhi.modules.model.OfficialServiceDefaults.LLM_TEMPERATURE);
        }
    }
}
