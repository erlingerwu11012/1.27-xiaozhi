import os,json
from pathlib import Path
os.environ['CANDIDATE_RUNTIME']='1'
s=Path(__file__).with_name('runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
exec(compile(s,'<bootstrap>','exec'))
from core.utils.conversation_turn import attach_conversation_evidence
from core.utils.dialogue import Message
question='刚买了个书架，还没发货。我就是随便聊聊，别替我安排。'
messages=attach_conversation_evidence([{'role':'system','content':prompt},{'role':'user','content':question}],[Message(role='user',content=question)])
if os.environ.get('PROBE_DIRECT')=='1':
 channel=json.loads(sql("SELECT JSON_OBJECT('key',`key`,'base_url',base_url) FROM one_api.channels WHERE id=8 AND status=1;"))
 assert channel['base_url']=='https://dashscope.aliyuncs.com/compatible-mode/v1'
 provider.client.close()
 from openai import OpenAI
 provider.client=OpenAI(api_key=channel['key'],base_url=channel['base_url'],max_retries=0,timeout=45)
rows=[]
for name in os.environ.get('PROBE_MODELS','qwen3.7-plus,qwen3-max,qwen3.8-max-0902').split(','):
 try:
  r=provider.client.chat.completions.create(model=name,messages=messages,temperature=0.3,max_tokens=250,extra_body={'enable_thinking':False})
  rows.append({'model':name,'response_model':r.model,'assistant':r.choices[0].message.content,'usage':r.usage.model_dump() if r.usage else None})
 except Exception as e:rows.append({'model':name,'error_type':type(e).__name__,'status':getattr(e,'status_code',None)})
provider.client.close()
(OUT/(os.environ.get('PROBE_REPORT', 'complete-chat-model-probe-direct' if os.environ.get('PROBE_DIRECT')=='1' else 'complete-chat-model-probe')+'.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2));print(json.dumps(rows,ensure_ascii=False))
