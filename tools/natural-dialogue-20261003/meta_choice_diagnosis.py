"""Three live tests of keeping definitions but explicitly disabling dispatch."""
from live_chain_acceptance import *
from core.providers.llm.openai.openai import LLMProvider
from core.utils.turn_context import render_turn_context
provider=LLMProvider(dict(llm,timeout=35,max_tokens=180));provider.client=provider.client.with_options(max_retries=0)
tools=json.loads((OUT/'live-gateway.json').read_text())['tools']
ctx=render_turn_context({'current_datetime':'2026-10-03 12:00:00','today_weekday':'星期六','timezone':'Asia/Shanghai','speaker':'测试用户'})
rows=[]
for t in ['你好，随便聊聊。','你可以有幽默感，但别撒娇。','别哄我，说说你真实的看法。']:
    check_budget()
    r=provider.client.chat.completions.create(model=provider.model_name,messages=[{'role':'system','content':prompt},{'role':'user','content':ctx+'\n[用户原话]\n'+t}],tools=tools,tool_choice='none',max_tokens=180,temperature=float(llm.get('temperature') or .7),extra_body={'enable_thinking':False})
    rows.append({'user':t,'response':r.choices[0].message.content})
(OUT/'meta-choice-diagnosis.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));print(json.dumps(rows,ensure_ascii=False))
