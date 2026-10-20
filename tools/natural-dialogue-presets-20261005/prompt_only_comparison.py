"""Paired actual-production-handler comparison: prompt change only.

No conversation checker, evidence injection, regeneration or text trimming.
Uses synthetic inputs and the existing permitted test credential; no writes.
"""
import ast,asyncio,hashlib,json,os,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.pop('CANDIDATE_RUNTIME',None)
bootstrap=Path(__file__).with_name('runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
exec(compile(bootstrap,'<production-bootstrap>', 'exec'))
provider.client.close()
from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests
from core.providers.tts.dto.dto import ContentType
from plugins_func.register import Action,ActionResponse
import core.utils.prompt_manager as prompt_module

OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
RESULT=OUT/'prompt-only-comparison.json'
assert ROOT==PROD and llm['model_name']=='qwen3.8-flash' and float(llm['temperature'])==0.4
assert 'conversation_turn' not in (ROOT/'core/connection.py').read_text(), 'production_handler_has_candidate_checker'

def constant(path,name):
    for node in ast.parse(path.read_text(encoding='utf-8-sig')).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('constant_missing')

new_guidance=constant(Path('/root/prjs/tmp/complete-chat-review-20261006/main/xiaozhi-server/core/utils/conversation_guidance.py'),'NATURAL_CONVERSATION_GUIDANCE')
original_guidance=prompt_module.NATURAL_CONVERSATION_GUIDANCE
variants={'current':original_guidance,'prompt_only':new_guidance}
profiles=[{'id':'natural','prompt':'你随和、坦诚，有自己的看法。用熟人之间自然的方式交谈。'},
          {'id':'existing-playful','prompt':PERSONA}]
scenarios=constant(OUT/'complete_chat_acceptance.py','scenarios')+constant(OUT/'complete_chat_heldout_acceptance.py','scenarios')+[
 ['订的马克杯商家还没接单，当然没寄。我只是聊聊，不用帮我安排。',
  '旧杯子没坏，我只是喜欢新杯子的颜色。',
  '别总是反问我，直接聊你的看法。',
  '我觉得日常用品好看一点，用起来也会开心一点。',
  '你怎么看这种感觉？先别分析我的性格。',
  '顺便说一下，今天拼图拼好了边框，中间还没拼。',
  '我只说边框拼好了，不是整幅拼图完成。',
  '更新一下，商家缺货，把杯子的订单取消了，没有发货。',
  '杯子订单取消了，拼图还是只有边框完成，不要混在一起。',
  '只按我说的，新杯子和拼图分别是什么状态？'],
 ['烤蛋糕要用的黄油刚拿出来，还没称重，也没开始打发。别给教程，我就是闲聊。',
  '这是我第一次试这个配方，不代表第一次做蛋糕。',
  '今天别逗我，也别每句都问我。',
  '有时配方写得很详细，实际做起来还是跟想的不一样。',
  '你觉得照着同一个配方做，成品为什么还是会不同？不用给操作步骤。',
  '换个事，明天想去游泳，泳池有没有开门我还不知道。',
  '你没有查过泳池营业时间，就不能说我明天肯定能去，对吧？',
  '刚决定明天不去了，游泳的计划取消，蛋糕的黄油仍只拿出来了。',
  '现在请给我一个建议，做蛋糕应该先确认哪件事？',
  '回到我说过的事实，游泳安排和黄油处理各进行到哪了？']]
assert len(scenarios)==10 and all(len(s)==10 for s in scenarios)
assert len({q for s in scenarios for q in s})==100
hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
        ['core/connection.py','core/utils/prompt_manager.py','core/utils/conversation_guidance.py',
         'core/utils/operation_control.py','core/providers/llm/openai/openai.py','agent-base-prompt-v2.txt']}
snapshot={'runtime_source_sha256':hashes,'guidance_sha256':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in variants.items()},
          'cases_sha256':hashlib.sha256(json.dumps(scenarios,ensure_ascii=False).encode()).hexdigest(),
          'model':llm['model_name'],'temperature':0.4,'max_tokens':450,'production_changes':False,
          'user_personality_modified':False,'semantic_validation':False,'chat_retry':False,
          'evidence_injection':False,'answer_trimming':False,'secondary_polishing':False,
          'hardware_writes':0,'physical_audio_test':False,'unique_inputs':100,'planned_turns':400}
data=json.loads(RESULT.read_text()) if RESULT.exists() else {**snapshot,'dialogues':[], 'completed':False,
    'calls':0,'usage':{'input_tokens':0,'output_tokens':0}}
assert all(data.get(k)==v for k,v in snapshot.items()), 'resume_snapshot_changed'
def save():RESULT.write_text(json.dumps(data,ensure_ascii=False,indent=2))

async def run():
    settings=json.loads((PROD/'data/.mcp_server_settings.json').read_text())['mcpServers']
    client=ServerMCPClient(next(c for c in settings.values() if not c.get('disabled',False)))
    await asyncio.wait_for(client.initialize(),20)
    definitions=client.get_available_tools();await client.cleanup()
    data['tool_catalog_count']=len(definitions)
    fixture=PrimaryAnswerDirectTtsTests();fixture.setUpClass()
    try:
      for profile in profiles:
       for scene,questions in enumerate(scenarios):
        for variant,guidance in variants.items():
         ident=f'{variant}/{profile["id"]}/{scene}'
         entry=next((d for d in data['dialogues'] if d['id']==ident),None)
         if entry is None:
            entry={'id':ident,'variant':variant,'persona':profile['id'],'persona_prompt':profile['prompt'],'scenario':scene,'turns':[]}
            data['dialogues'].append(entry)
         fixture.setUp();h=fixture.handler();h.actor.key=('synthetic','prompt-only',1)
         h.config['operation_control']={'enabled':True}
         assert 'conversation_validation' not in h.config
         # One selected system string, frozen for this synthetic dialogue.
         prompt_module.NATURAL_CONVERSATION_GUIDANCE=guidance
         system=PromptManager({'system_base_prompt':base.get('system_base_prompt',''),'language':'中文'},logger=MagicMock()).build_enhanced_prompt_v2(profile['prompt'],'synthetic-prompt-only',device_name='小智',user_nickname='主人',official_enhanced=True)
         prompt_module.NATURAL_CONVERSATION_GUIDANCE=original_guidance
         assert guidance.strip() in system and profile['prompt'] in system
         entry['system_sha256']=hashlib.sha256(system.encode()).hexdigest()
         h.dialogue.update_system_message(system)
         h.llm=LLMProvider(dict(llm,timeout=45,max_tokens=450));h.llm.client=h.llm.client.with_options(max_retries=0)
         original_create=h.llm.client.chat.completions.create
         metadata={};proposals=[];deliveries=[]
         enqueue=h.enqueue_tts
         def deliver(event):
            if event.content_type==ContentType.TEXT:deliveries.append(time.perf_counter())
            enqueue(event)
         h.enqueue_tts=deliver
         def capture(_create=original_create,**params):
            assert not str(params['messages'][0].get('content','')).startswith('你是回应发送前的事实与要求校验器')
            assert not any('[本轮回应检查' in str(msg.get('content','')) for msg in params['messages'])
            assert not any('[程序校验反馈' in str(msg.get('content','')) for msg in params['messages'])
            metadata['requests']=metadata.get('requests',0)+1
            params['stream_options']={'include_usage':True}
            response=_create(**params)
            def chunks():
                text=[];usage={}
                for chunk in response:
                    metadata['response_model']=chunk.model
                    for choice in chunk.choices or []:
                        if choice.finish_reason:metadata.setdefault('finish_reasons',[]).append(choice.finish_reason)
                        if choice.delta.content:
                            text.append(choice.delta.content)
                            metadata.setdefault('first_text_at',time.perf_counter())
                    if chunk.usage:usage=chunk.usage.model_dump()
                    yield chunk
                metadata.setdefault('original_outputs',[]).append(''.join(text))
                total=metadata.setdefault('usage',{'prompt_tokens':0,'completion_tokens':0})
                for k in total:total[k]+=int(usage.get(k,0))
            return chunks()
         h.llm.client.chat.completions.create=capture
         async def deny(conn,call):
            proposals.append(call)
            return ActionResponse(action=Action.ERROR,response='聊天对照未授权外部操作，未执行。')
         h.func_handler=SimpleNamespace(get_functions=lambda:definitions,handle_llm_function_call=deny)
         try:
          for index,question in enumerate(questions,1):
           if index<=len(entry['turns']):
            h.dialogue.put(Message(role='user',content=question));h.dialogue.put(Message(role='assistant',content=entry['turns'][index-1]['assistant']));continue
           assert data['calls']<400 and data['usage']['input_tokens']<2200000 and data['usage']['output_tokens']<100000,'bounded_test_budget'
           metadata.clear();proposals.clear();deliveries.clear();h.tts_events.clear()
           begin=time.perf_counter();data['calls']+=1
           ok=await asyncio.to_thread(lambda:h.chat(question,_identity=h.actor))
           reply=''.join(str(e.content_detail) for e in h.tts_events if e.content_type==ContentType.TEXT)
           usage=metadata.get('usage') or {}
           for dest,src in [('input_tokens','prompt_tokens'),('output_tokens','completion_tokens')]:data['usage'][dest]+=int(usage.get(src,0))
           row={'turn':index,'user':question,'assistant':reply,'pipeline_completed':bool(ok),
                'request_count':metadata.get('requests',0),'response_model':metadata.get('response_model'),
                'elapsed_ms':round((time.perf_counter()-begin)*1000),
                'first_primary_text_ms':round((metadata['first_text_at']-begin)*1000) if 'first_text_at' in metadata else None,
                'first_tts_enqueue_ms':round((deliveries[0]-begin)*1000) if deliveries else None,
                'finish_reasons':metadata.get('finish_reasons',[]),'original_outputs':metadata.get('original_outputs',[]),
                'tool_proposals':list(proposals),'usage':usage,'conversation_check':getattr(h,'_conversation_gate',None)}
           assert row['conversation_check'] is None
           entry['turns'].append(row);save();print(json.dumps({'id':ident,**row},ensure_ascii=False),flush=True)
           assert ok and reply and row['response_model'],'upstream_or_pipeline_failed'
         finally:h.llm.client.close();fixture.doCleanups()
    finally:prompt_module.NATURAL_CONVERSATION_GUIDANCE=original_guidance;fixture.tearDownClass()
    data['completed']=data['calls']==400;data['quality_passed']=None;save()
    print(json.dumps({'completed':data['completed'],'turns':data['calls'],'usage':data['usage']},ensure_ascii=False))

asyncio.run(run())
