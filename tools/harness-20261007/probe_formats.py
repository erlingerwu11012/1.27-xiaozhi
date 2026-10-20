import json
from bootstrap import production_provider,stage
from core.utils.hardware_billing import request_headers
p,c=production_provider()
base={'model':p.model_name,'temperature':.4,'stream':False,'max_tokens':150,'extra_body':{'enable_thinking':False,'preserve_thinking':False},'extra_headers':request_headers(p.hardware_context['account_id'],'llm')}
evidence={}
try:
    r=p.client.with_options(max_retries=0,timeout=30).chat.completions.create(**base,messages=[{'role':'user','content':'Return a JSON object containing mode chat and reply hello.'}],response_format={'type':'json_schema','json_schema':{'name':'decision_probe','strict':True,'schema':{'type':'object','properties':{'mode':{'type':'string','enum':['chat']},'reply':{'type':'string'}},'required':['mode','reply'],'additionalProperties':False}}})
    evidence['json_schema']={'supported':True,'content':r.choices[0].message.content}
except Exception as e:evidence['json_schema']={'supported':False,'error_type':type(e).__name__,'status':getattr(e,'status_code',None)}
from test_support import PACK
tools=[{k:v for k,v in t.items() if k!='source'} for t in PACK['tools'] if t['function']['name'] in {'self_get_device_status','get_world_time'}]
try:
    base['extra_headers']=request_headers(p.hardware_context['account_id'],'llm')
    r=p.client.with_options(max_retries=0,timeout=30).chat.completions.create(**base,messages=[{'role':'user','content':'查询设备当前状态。'}],tools=tools,tool_choice={'type':'function','function':{'name':'get_world_time'}})
    names=[t.function.name for t in r.choices[0].message.tool_calls or []]
    evidence['specific_tool_choice']={'supported':names==['get_world_time'],'returned_tools':names}
except Exception as e:evidence['specific_tool_choice']={'supported':False,'error_type':type(e).__name__,'status':getattr(e,'status_code',None)}
from core.utils.tool_harness.models import Decision
try:
    base['extra_headers']=request_headers(p.hardware_context['account_id'],'llm')
    r=p.client.with_options(max_retries=0,timeout=30).chat.completions.create(**base,messages=[{'role':'user','content':'Return Decision JSON with mode chat, reply hello, goal empty, steps empty, finished true, authorized_writes empty.'}],response_format={'type':'json_schema','json_schema':{'name':'harness_decision','strict':True,'schema':Decision.model_json_schema()}})
    value=Decision.model_validate_json(r.choices[0].message.content)
    evidence['decision_schema']={'supported':True,'value':value.model_dump()}
except Exception as e:evidence['decision_schema']={'supported':False,'error_type':type(e).__name__,'status':getattr(e,'status_code',None)}
(stage/'format-probes.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print(json.dumps(evidence,ensure_ascii=False))
