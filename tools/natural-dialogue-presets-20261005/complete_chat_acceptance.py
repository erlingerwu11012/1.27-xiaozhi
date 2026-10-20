"""Single-pass production-handler acceptance; synthetic personas and inputs only."""
import asyncio, hashlib, json, os, re, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ['CANDIDATE_RUNTIME'] = '1'
source = Path(__file__).with_name('runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
exec(compile(source, '<acceptance-bootstrap>', 'exec'))
provider.client.close()
from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests
from core.providers.tts.dto.dto import ContentType
from plugins_func.register import Action, ActionResponse

name = os.environ.get('CHAT_REPORT', 'complete-chat-pilot')
path = OUT / (name + '.json')
models = os.environ.get('CHAT_MODELS', 'qwen3.8-flash,qwen3.8-max').split(',')
node = "import {readFileSync} from 'node:fs';let m=await import('data:text/javascript;base64,'+readFileSync(process.argv[1]).toString('base64'));console.log(JSON.stringify(m.PERSONA_PRESETS));"
profiles = json.loads(subprocess.run(['node', '--input-type=module', '-e', node, str(PROD.parent / 'manager-web/src/constants/personaPresets.js')], capture_output=True, text=True, check=True).stdout)
profiles.append({'id': 'existing-playful', 'prompt': PERSONA})

scenarios = [
 ['刚买了个书架，还没发货。我就是随便聊聊，别替我安排。',
  '现在家里还没有这个新书架，我期待把以前的书重新摆出来。',
  '别每句话都反问我，你直接说说看法。',
  '有时候重看以前的书，感觉跟当年完全不一样。',
  '今天先别逗我，也别说慢慢来。我只是说说这些小事。',
  '有本书以前看不进去，现在反而喜欢了。你觉得这是为什么？',
  '报告上周已经写好一半，昨天只改标题，剩下正文还没碰。',
  '昨天正文没进展，能说整份报告正文从来没写过吗？',
  '更新一下，店家刚通知书架已经发货了，但我还没有收到。',
  '只根据我说过的内容，书架现在什么状态，报告完成了多少？'],
 ['今天两个会都白开了，我有点烦。别给方案，也别劝休息。',
  '开完也没结论，明天可能还得再开，但还没确定。',
  '别教育我，也不用一直问我问题，聊两句就行。',
  '有时候大家都在说话，但就是谈不到一个点上。',
  '我觉得问题不是时间长，而是没人真正把分歧说清楚。',
  '说说你的看法，不用告诉我该怎么开会。',
  '换个话题，我打算周末去逛展，只是打算，还没买票。',
  '有些画现场看跟手机看完全两回事。你怎么看？',
  '刚看了下安排，这周末不去展了，改成下周再考虑，也没买票。',
  '按我实际说过的内容，我现在确定去展了吗，票买了吗？'],
 ['刚下单一个电饭煲，店家后天才发货，现在还没有寄出。别给建议。',
  '以前那个还能用，我不是急着换，只是喜欢新的外形。',
  '别拿我开玩笑，别反问，就正常接话。',
  '有时买个日常小东西，比买贵东西还期待。',
  '你说说为什么会这样，别替我分析童年经历。',
  '我昨晚做饭只切了菜，后来停了，还没下锅。',
  '不是饭已经做好了，只是菜切好了，你按这个理解。',
  '话说有些菜光看名字就觉得好吃，实际上却一般。',
  '刚收到店家消息，电饭煲缺货，订单取消了，没有发货。',
  '只按我说过的话，现在订单怎么样，昨晚饭做到了哪一步？'],
 ['最近又开始学吉他了，一首曲子练完前半段，后半段还没练。先别指导我。',
  '我没有报名课程，是自己照着谱子弹的。',
  '今天别逗我，也别总是反问。',
  '有首老歌以前觉得普通，现在觉得旋律挺好。',
  '你觉得一首歌为什么会在不同年龄听出不同感觉？',
  '我打算换琴弦，只是打算，还没有买，也没换。',
  '我不是说整首曲子都不会弹，前半段已经能弹下来。',
  '不需要给练习计划，我们就聊聊听歌。',
  '更新一下，琴弦刚买了，店家还没发货，当然也还没有换。',
  '只按我说过的情况，曲子练到哪了，琴弦是什么状态？'],
 ['朋友本来约我周五吃饭，不过他还没确认有没有空。我想聊聊，不要建议。',
  '我也没订餐厅，现在只是聊到这个想法。',
  '别一直反问我，说说你的看法就行。',
  '以前楼下喊一声就能见面，现在吃个饭都要看日历。',
  '成年人的朋友为什么越来越难约？别给我行动方案。',
  '我们不是吵架也不是闹矛盾，只是还没约成。',
  '今天先别调侃我，认真聊两句就行。',
  '有人很久不见，再见面聊天又很自然，我觉得挺难得。',
  '刚刚他说周五没空，所以这次没约成，也没改约其他日期。',
  '只按我刚说过的内容，这次饭约成了吗，餐厅订了吗？'],
]
if os.environ.get('CHAT_FULL') != '1':
    profiles = [profiles[0], profiles[-1]]
    scenarios = scenarios[:1]

source_hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in [
 'core/connection.py','core/utils/conversation_guidance.py','core/utils/conversation_turn.py']}
result = json.loads(path.read_text()) if path.exists() else {
 'source': 'actual candidate ConnectionHandler; bounded primary retry; same-provider semantic validation; full real MCP catalog; no writes',
 'runtime_source_sha256':source_hashes,'semantic_enabled':os.environ.get('CHAT_SEMANTIC')=='1',
 'physical_voice_test': False, 'hardware_writes': 0, 'secondary_rewrite': False,
 'dialogues': [], 'completed': False, 'calls': 0, 'usage': {'input_tokens': 0, 'output_tokens': 0}}
assert result.get('runtime_source_sha256')==source_hashes, 'resume_source_changed'
max_calls = len(models)*len(profiles)*len(scenarios)*10

def save():
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2))

async def run():
    settings=json.loads((PROD/'data/.mcp_server_settings.json').read_text())['mcpServers']
    client=ServerMCPClient(next(c for c in settings.values() if not c.get('disabled', False)))
    await client.initialize()
    definitions=client.get_available_tools()
    await client.cleanup()
    result['tool_catalog_count']=len(definitions)
    test=PrimaryAnswerDirectTtsTests();test.setUpClass()
    try:
      for model in models:
       for profile in profiles:
        for scenario_index, questions in enumerate(scenarios):
         key=f'{model}/{profile["id"]}/{scenario_index}'
         entry=next((d for d in result['dialogues'] if d['id']==key), None)
         if entry is None:
            entry={'id':key,'model':model,'persona':profile['id'],'scenario':scenario_index,'turns':[]}
            result['dialogues'].append(entry)
         test.setUp();h=test.handler();h.actor.key=('synthetic','voice',1)
         h.config['operation_control']={'enabled': True}
         h.config['conversation_validation']={'semantic_enabled': os.environ.get('CHAT_SEMANTIC')=='1'}
         system=PromptManager({'system_base_prompt':base.get('system_base_prompt',''),'language':'中文'}, logger=MagicMock()).build_enhanced_prompt_v2(profile['prompt'],'synthetic-acceptance',device_name='小智', official_enhanced=True)
         entry['system_sha256']=hashlib.sha256(system.encode()).hexdigest()
         h.dialogue.update_system_message(system)
         h.llm=LLMProvider(dict(llm,model_name=model,temperature=0.3,timeout=45,max_tokens=250))
         if os.environ.get('CHAT_DIRECT_ALI')=='1':
            h.llm.client.close()
            direct_key=sql('SELECT `key` FROM one_api.channels WHERE id=8;').strip()
            h.llm=LLMProvider(dict(llm,model_name=model,temperature=0.3,timeout=45,max_tokens=250,
               api_key=direct_key,base_url='https://dashscope.aliyuncs.com/compatible-mode/v1'))
         h.llm.client=h.llm.client.with_options(max_retries=0)
         # Capture one primary request's metadata without logging credentials or
         # reasoning. Configured thinking is a primary mode, not a second pass.
         original_create=h.llm.client.chat.completions.create
         metadata={}
         def capture(_create=original_create, **params):
            metadata['request_count']=metadata.get('request_count',0)+1
            params['stream_options']={'include_usage':True}
            if model.startswith(('qwen','deepseek','kimi')) and os.environ.get('CHAT_THINKING')!='1':
                params['extra_body']={'enable_thinking':False,'preserve_thinking':False}
            if os.environ.get('CHAT_THINKING')=='1':
                params['extra_body']={'enable_thinking':True,'preserve_thinking':False,
                                      'thinking_budget':1024}
                params['max_tokens']=4096
            response=_create(**params)
            def chunks():
                text_parts=[]
                attempt_usage={}
                for chunk in response:
                    metadata['response_model']=chunk.model
                    for choice in chunk.choices or []:
                        if choice.finish_reason:metadata.setdefault('finish_reasons',[]).append(choice.finish_reason)
                    if chunk.usage:attempt_usage=chunk.usage.model_dump()
                    for choice in chunk.choices or []:
                        if choice.delta.content:text_parts.append(choice.delta.content)
                    yield chunk
                if params['messages'][0].get('content','').startswith('你是回应发送前的事实与要求校验器'):
                    metadata.setdefault('semantic_verdicts',[]).append(''.join(text_parts))
                else:
                    metadata.setdefault('generated_attempts',[]).append(''.join(text_parts))
                accumulated=metadata.setdefault('usage',{'prompt_tokens':0,'completion_tokens':0})
                for token_key in accumulated:
                    accumulated[token_key]+=int(attempt_usage.get(token_key,0))
            return chunks()
         h.llm.client.chat.completions.create=capture
         tool_events=[]
         async def block(conn, call):
            tool_events.append(call)
            return ActionResponse(action=Action.RESPONSE,response='隔离聊天验收未授权操作，未执行。')
         h.func_handler=SimpleNamespace(get_functions=lambda:definitions, handle_llm_function_call=block)
         try:
          for index, question in enumerate(questions,1):
           if index <= len(entry['turns']):
            h.dialogue.put(Message(role='user', content=question));h.dialogue.put(Message(role='assistant',content=entry['turns'][index-1]['assistant']));continue
           assert result['calls'] < max_calls and result['usage']['input_tokens'] < 2200000 and result['usage']['output_tokens'] < 90000, 'bounded_test_budget'
           h.tts_events.clear();tool_events.clear();metadata.clear();start=time.perf_counter();result['calls']+=1
           ok=await asyncio.to_thread(lambda:h.chat(question,_identity=h.actor))
           answer=''.join(str(e.content_detail) for e in h.tts_events if e.content_type == ContentType.TEXT)
           usage=metadata.get('usage') or {}
           result['usage']['input_tokens']+=int(usage.get('prompt_tokens',0))
           result['usage']['output_tokens']+=int(usage.get('completion_tokens',0))
           row={'turn':index,'user':question,'assistant':answer,'pipeline_completed':bool(ok),'tool_proposals':list(tool_events),'elapsed_ms':round((time.perf_counter()-start)*1000),
                'request_count':metadata.get('request_count'), 'response_model':metadata.get('response_model'),'usage':usage}
           row['generated_attempts']=metadata.get('generated_attempts',[])
           row['semantic_verdicts']=metadata.get('semantic_verdicts',[])
           row['draft_generations']=len(row['generated_attempts'])
           row['validator_requests']=len(row['semantic_verdicts'])
           row['finish_reasons']=metadata.get('finish_reasons',[])
           row['upstream_observed']=bool(metadata.get('response_model'))
           row['output_truncated']='length' in row['finish_reasons']
           row['response_check']=getattr(h,'_conversation_gate',None)
           entry['turns'].append(row);save();print(json.dumps({'id':key,**row}, ensure_ascii=False),flush=True)
           if not ok or not answer: raise RuntimeError('pipeline_failed')
           if not row['upstream_observed']:raise RuntimeError('upstream_not_observed')
         finally:
          h.llm.client.close();test.doCleanups()
    finally:
      test.tearDownClass()
    result['completed']=result['calls']==max_calls
    result['quality_passed']=None # Set only after reviewing the actual responses.
    save();print(json.dumps({'completed':result['completed'],'calls':result['calls'],'usage':result['usage']}))

asyncio.run(run())
