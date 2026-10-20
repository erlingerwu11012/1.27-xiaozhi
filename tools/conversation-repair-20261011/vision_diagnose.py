import bootstrap,json
from bootstrap import production_provider,stage
p,c=production_provider();p.client.close()
for name,cfg in [('runtime',c),('device',json.loads(open('/root/prjs/tmp/harness-20261007/private-backup/device-config.json').read()))]:
 key=cfg.get('selected_module',{}).get('VLLM');v=cfg.get('VLLM',{}).get(key,{})
 print(name,{'selection':key,'type':v.get('type'),'model':v.get('model_name'),'has_key':bool(v.get('api_key')),'billing':bool(v.get('hardware_billing')),'has_billing_account':bool(v.get('hardware_account_id'))})
from core.providers.vllm.openai import VLLMProvider
v=c['VLLM'][c['selected_module']['VLLM']];provider=VLLMProvider(v)
from urllib.parse import urlparse
u=urlparse(str(provider.base_url));print('endpoint',{'host':u.hostname,'port':u.port,'path':u.path})
provider.client.max_retries=0
from bootstrap import budget
charge=budget.reserve('vision','diagnose-real-vlm');budget.reserve('case','diagnose-real-vlm')
try:
 text=provider.response('图片主要是什么颜色？',(stage/'synthetic-blue-jpeg.b64').read_text());print('VLM_RESPONSE',text);budget.finish(charge,{'success':True,'text':text})
except Exception as exc:
 meta={'success':False,'type':type(exc).__name__,'status':getattr(exc,'status_code',None),'code':getattr(exc,'code',None)}
 print('VLM_ERROR',meta);budget.finish(charge,meta)
finally:provider.client.close()
