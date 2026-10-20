"""Three repetitions of difficult live style cases, preserving customer personas."""
from concurrent.futures import ThreadPoolExecutor
import threading
from live_chain_acceptance import *
from core.utils.operation_control import guard_reply, OperationControl
from core.providers.llm.openai.openai import LLMProvider
from core.utils.turn_context import render_turn_context
provider=LLMProvider(dict(llm,timeout=35,max_tokens=230))
provider.client=provider.client.with_options(max_retries=0)
tools=json.loads((OUT/'live-gateway.json').read_text())['tools']
subjects=['你好，随便聊聊。','我今天有点烦，先别开玩笑。','我刚失业，不知道下一步怎么办。',
    '别哄我，说说你真实的看法。','你可以有幽默感，但别撒娇。','给我讲一个短故事。',
    '我不喜欢你每句话都问我一个问题。','如果我不同意你的观点，你会怎么聊？',
    '聊聊一个你觉得有意思的科学问题。','我们能正常聊一会儿吗？',
    '我今天完成了一个一直拖着的任务。','我做事总拖延，你怎么看？',
    '今天累了，不想动脑子。','我需要认真讨论一个项目方案。',
    '23乘以17等于多少？','解释一下天空为什么是蓝色的。',
    '你觉得成年人最难的事情是什么？','我和朋友吵架了，怎么把话说清楚？',
    '你会怎么回应别人不合理的要求？','人为什么会害怕拒绝别人？']
items=[{'text':t,'repeat':r,'persona':PERSONA} for r in range(1,4) for t in subjects]
for persona in ['你严谨、直接，喜欢用准确的例子解释问题。','你随和、有幽默感，喜欢轻松地聊天。','你活泼可爱，用户明确希望你用撒娇的口吻聊天。']:
    for t in ['今天累了，不想动脑子。','如果我不同意你的观点，你会怎么聊？']:
        items.append({'text':t,'repeat':1,'persona':persona})
lock=threading.Lock();count=0
pattern=r'好不好呀|乖乖|小主人|嘻嘻|嘿嘿|人家|小尾巴|小脑袋瓜|[（(](?:眨眼|眨眨眼|歪头|捂嘴|叉腰|偷笑)|(?:主人.*[～~])'
def run(item):
    global count
    with lock:
        assert count<70,'model_call_guard';check_budget();count+=1
    system=prompt if item['persona']==PERSONA else PromptManager({'system_base_prompt':base.get('system_base_prompt',''),'language':'中文'},logger=MagicMock()).build_enhanced_prompt_v2(item['persona'],'style-test',device_name='小智',official_enhanced=True)
    context=render_turn_context({'current_datetime':'2026-10-03 12:00:00','today_weekday':'星期六','timezone':'Asia/Shanghai','speaker':'测试用户'})
    start=time.perf_counter()
    try:
        control=OperationControl();plan=control.begin(item['text'],('s','p'))
        response=provider.client.chat.completions.create(model=provider.model_name,messages=[{'role':'system','content':system},{'role':'user','content':context+'\n[用户原话]\n'+item['text']}],tools=tools,tool_choice='none' if control.chat_only else 'auto',max_tokens=230,temperature=float(llm.get('temperature') or .7),top_p=float(llm.get('top_p') or 1),extra_body={'enable_thinking':False})
        raw=response.choices[0].message.content or ''
        delivered=plan.reply or guard_reply(SimpleNamespace(config={'operation_control':{'enabled':True}},_operation_control=control),raw)
        return dict(item,raw=raw,delivered=delivered,program_clarification=bool(plan.reply),flags=bool(re.search(pattern,delivered)),calls=[c.function.name for c in response.choices[0].message.tool_calls or []],persona_preserved=item['persona'] in system,elapsed_ms=round((time.perf_counter()-start)*1000))
    except Exception as exc:return dict(item,error_type=type(exc).__name__)
with ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(run,items))
(OUT/'style-revalidation.json').write_text(json.dumps({'calls':count,'maximum_calls':70,'cases':rows,'manual_review_required':True},ensure_ascii=False,indent=2))
print(json.dumps({'calls':count,'errors':sum('error_type' in c for c in rows),'default_persona_flags':sum(c.get('flags',False) for c in rows if c['persona']==PERSONA),'preserved':all(c.get('persona_preserved',False) for c in rows)},ensure_ascii=False))
