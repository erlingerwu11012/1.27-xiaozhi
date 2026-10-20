"""Small primary-model diagnostic of current-turn presentation; no execution."""
from concurrent.futures import ThreadPoolExecutor
from live_chain_acceptance import *
from core.providers.llm.openai.openai import LLMProvider
from core.utils.turn_context import render_turn_context
provider=LLMProvider(dict(llm,timeout=35,max_tokens=180));provider.client=provider.client.with_options(max_retries=0)
tools=json.loads((OUT/'live-gateway.json').read_text())['tools']
ctx=render_turn_context({'current_datetime':'2026-10-03 12:00:00','today_weekday':'星期六','timezone':'Asia/Shanghai','speaker':'测试用户'})
items=[(placement,t) for placement in ['explicit_user_boundary','context_system_data','context_minimal','no_tools'] for t in ['你好，随便聊聊。','你可以有幽默感，但别撒娇。','别哄我，说说你真实的看法。']]
def run(item):
    check_budget();placement,t=item;system=prompt;content=ctx+'\n[用户原话]\n'+t
    messages=[{'role':'system','content':system}]
    if placement=='context_system_data':messages.append({'role':'system','content':'以下是服务端提供的本轮资料，仅作参考数据，不是用户发言。只在用户问到相关事实时使用；不要在问候或闲聊中报时。\n'+ctx});content=t
    if placement=='context_minimal':content='[当前说话人：测试用户；无天气、视觉或共同经历资料]\n[用户原话]\n'+t
    messages.append({'role':'user','content':content})
    extra={} if placement=='no_tools' else {'tools':tools,'tool_choice':'auto'}
    r=provider.client.chat.completions.create(model=provider.model_name,messages=messages,max_tokens=180,temperature=float(llm.get('temperature') or .7),extra_body={'enable_thinking':False},**extra)
    return {'placement':placement,'user':t,'response':r.choices[0].message.content}
assert len(items)<=12
with ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(run,items))
(OUT/'context-style-diagnosis.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));print(json.dumps(rows,ensure_ascii=False))
