"""Account-scoped hardware providers; switches stay off until gateway tests pass."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]/'tmp/hardware-billing70/server'

def patch(path,old,new):
    p=ROOT/path;s=p.read_text(encoding='utf-8')
    if new in s:return
    if s.count(old)!=1:raise RuntimeError('source mismatch: '+path)
    p.write_text(s.replace(old,new),encoding='utf-8',newline='\n')

llm='main/xiaozhi-server/core/providers/llm/openai/openai.py'
patch(llm,'from core.utils import trace_log as trace', '''from core.utils import trace_log as trace
from core.utils.hardware_billing import provider_context, request_headers, sign_request''')
patch(llm,'self.model_name = config.get("model_name")', '''self.hardware_context = provider_context(config)
        self.model_name = config.get("model_name")''')
patch(llm,'default_encoding="utf-8",', '''default_encoding="utf-8",
                event_hooks={"request": [sign_request]} if self.hardware_context else None,''')
p=ROOT/llm;s=p.read_text(encoding='utf-8')
old='''            if self.aimi_device_gateway:
                request_params["extra_headers"] = self._aimi_headers(session_id)'''
new='''            if self.hardware_context:
                request_params["extra_headers"] = request_headers(
                    self.hardware_context["account_id"],
                    kwargs.get("billing_operation", self.hardware_context["operation"]))
                request_params["stream_options"] = {"include_usage": True}
            if self.aimi_device_gateway:
                request_params["extra_headers"] = self._aimi_headers(session_id)'''
if new not in s:
    if s.count(old)!=2:raise RuntimeError('provider call-site mismatch')
    s=s.replace(old,new);p.write_text(s,encoding='utf-8',newline='\n')

vision='main/xiaozhi-server/core/providers/vllm/openai.py'
patch(vision,'import json', '''import json
import httpx
from core.utils.hardware_billing import provider_context, request_headers, sign_request''')
patch(vision,'self.model_name = config.get("model_name")', '''self.hardware_context = provider_context(config)
        self.model_name = config.get("model_name")''')
patch(vision,'self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)', '''self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url,
            http_client=httpx.Client(event_hooks={"request": [sign_request]} if self.hardware_context else None))''')
patch(vision,'model=self.model_name, messages=messages, stream=False', '''model=self.model_name, messages=messages, stream=False,
                extra_headers=request_headers(self.hardware_context["account_id"], "vision") if self.hardware_context else None''')

config='main/manager-api/src/main/java/xiaozhi/modules/config/service/impl/ConfigServiceImpl.java'
patch(config,'private final OfficialTtsService officialTtsService;', '''private final OfficialTtsService officialTtsService;
    private final xiaozhi.modules.pay.service.HardwareBillingPolicy hardwareBillingPolicy;''')
patch(config,'typeConfig.put(model.getId(), copied);', '''hardwareBillingPolicy.configure(copied,result,modelTypes[i],"llm");
                typeConfig.put(model.getId(), copied);''')
# Additional memory/intent model maps must be copied before assigning a personal key.
for var,operation in [('intentLLM','llm'),('memLocalShortLLM','summary')]:
    old=f'typeConfig.put({var}.getId(), {var}.getConfigJson());'
    new=f'''Map<String,Object> extraCopy=JsonUtils.parseObject(JsonUtils.toJsonString({var}.getConfigJson()),
                                    new com.fasterxml.jackson.core.type.TypeReference<Map<String,Object>>() {{}});
                            if(extraCopy==null) extraCopy=new HashMap<>();
                            hardwareBillingPolicy.configure(extraCopy,result,"LLM","{operation}");
                            typeConfig.put({var}.getId(),extraCopy);'''
    patch(config,old,new)

print('candidate hardware LLM/vision account routing patched; activation still off')
