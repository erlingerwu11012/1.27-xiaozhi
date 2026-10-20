import bootstrap
import json,time
from urllib.parse import urlsplit
provider,cfg=bootstrap.production_provider();start=time.monotonic()
answer=provider.decision([{'role':'system','content':'只输出JSON对象，mode=chat，reply回答你好，steps为空数组，goal为空字符串。'},{'role':'user','content':'你好'}])
out={'passed':True,'model':provider.model_name,'gateway_host':urlsplit(provider.base_url).hostname,'billing_enabled':bool(provider.hardware_context),'non_thinking':True,'answer':answer,'usage':provider.last_usage,'elapsed_ms':round((time.monotonic()-start)*1000)}
(bootstrap.stage/'model-probe.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False));provider.client.close()
