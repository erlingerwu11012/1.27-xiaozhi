"""Compare decoding settings without changing production configuration."""
from concurrent.futures import ThreadPoolExecutor
from live_chain_acceptance import *
from core.providers.llm.openai.openai import LLMProvider
from core.utils.turn_context import render_turn_context
provider=LLMProvider(dict(llm,timeout=35,max_tokens=200));provider.client=provider.client.with_options(max_retries=0)
tools=json.loads((OUT/'live-gateway.json').read_text())['tools']
ctx=render_turn_context({'current_datetime':'2026-10-03 12:00:00','today_weekday':'星期六','timezone':'Asia/Shanghai','speaker':'测试用户'})
items=[(temp,t) for temp in [0.2,0.5] for t in ['你好，随便聊聊。','你可以有幽默感，但别撒娇。','别哄我，说说你真实的看法。']]
def run(item):
    check_budget();temp,t=item
    r=provider.client.chat.completions.create(model=provider.model_name,messages=[{'role':'system','content':prompt},{'role':'user','content':ctx+'\n[用户原话]\n'+t}],tools=tools,tool_choice='auto',max_tokens=200,temperature=temp,extra_body={'enable_thinking':False})
    return {'temperature':temp,'user':t,'response':r.choices[0].message.content}
with ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(run,items))
(OUT/'temperature-diagnosis.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));print(json.dumps(rows,ensure_ascii=False))
