"""Small, read-only model probe; expose only route and upstream error metadata."""
import json,hashlib,time
from bootstrap import production_provider,stage
provider,cfg=production_provider()
print(json.dumps({'base_url':provider.base_url,'model':provider.model_name,
                  'hardware_billing':bool(provider.hardware_context),
                  'account_fingerprint':hashlib.sha256(provider.hardware_context['account_id'].encode()).hexdigest()[:12]}),flush=True)
results=[]
for user in ['随便聊聊，今天重看旧书觉得和以前不同。','把当前提醒标记为完成，谢谢','请用摄像头识别面前是谁']:
    start=time.monotonic()
    try:
        result=provider.decision([{'role':'system','content':'只输出JSON，格式为{"mode":"chat","reply":"简短回答","steps":[]}，不要执行任何工具。'},
                                  {'role':'user','content':user}])
        record={'success':True,'decision':result,'usage':provider.last_usage}
    except Exception as e:
        body=getattr(e,'body',None)
        record={'success':False,'type':type(e).__name__,'status':getattr(e,'status_code',None),'error_body':body if isinstance(body,dict) else None}
    record.update({'user':user,'elapsed_ms':round((time.monotonic()-start)*1000,2)})
    results.append(record);print(json.dumps(record,ensure_ascii=False),flush=True)
(stage/'current-route-probe.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
