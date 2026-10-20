"""Counterbalanced real primary-model latency, same real tool catalog, no writes."""
from live_chain_acceptance import *
from core.providers.llm.openai.openai import LLMProvider
from core.utils.operation_control import OperationControl,guard_reply
from core.utils.turn_context import render_turn_context
from core.providers.tts.official.compiler import caption_from
import statistics
provider=LLMProvider(dict(llm,timeout=35,max_tokens=220));provider.client=provider.client.with_options(max_retries=0)
tools=json.loads((OUT/'device-live-catalog.json').read_text())['tools']
ctx=render_turn_context({'current_datetime':'2026-10-03 12:00:00','today_weekday':'星期六','timezone':'Asia/Shanghai','speaker':'测试用户'})
baseline_code="""import os,sys;from unittest.mock import MagicMock;os.chdir(sys.argv[1]);sys.path.insert(0,sys.argv[1]);import config.logger;config.logger.setup_logging=lambda:MagicMock();from core.utils.prompt_manager import PromptManager;print(PromptManager({'system_base_prompt':sys.argv[2],'language':'中文'},logger=MagicMock()).build_enhanced_prompt_v2(sys.argv[3],'synthetic-acceptance',device_name='小智',user_nickname='主人',official_enhanced=True))"""
baseline=subprocess.run([sys.executable,'-c',baseline_code,str(PROD),base.get('system_base_prompt',''),PERSONA],capture_output=True,text=True,check=True).stdout.strip()
cases=['你好，随便聊聊。','我今天有点烦，先别开玩笑。','我刚失业，不知道下一步怎么办。',
'今天累了，不想动脑子。','23乘以17等于多少？','解释一下天空为什么是蓝色的。',
'我需要认真讨论一个项目方案。','我不喜欢你每句话都问我一个问题。',
'你可以有幽默感，但别撒娇。','如果我不同意你的观点，你会怎么聊？',
'我们能正常聊一会儿吗？','我今天完成了一个一直拖着的任务。']
assert len(cases)*2<=30
rows=[]
for idx,text in enumerate(cases):
    pair={}
    for label in (['baseline','candidate'] if idx%2==0 else ['candidate','baseline']):
        check_budget();control=OperationControl();control.begin(text,('s','p'))
        choice='none' if label=='candidate' and control.chat_only else 'auto'
        msg=[{'role':'system','content':baseline if label=='baseline' else prompt},
             {'role':'user','content':ctx+('\n[用户原话]' if label=='candidate' else '')+'\n'+text}]
        start=time.perf_counter();parts=[];first=None;calls=[]
        # Actual primary provider request/stream parsing; valid native fields remain fields.
        for content,tc in provider.response_with_functions('synthetic-latency',msg,functions=tools,tool_choice=choice,max_tokens=220):
            if first is None and (content or tc):first=time.perf_counter()-start
            if content:parts.append(content)
            if tc:calls.extend(c.function.name for c in tc if c.function.name)
        end=time.perf_counter()-start;raw=''.join(parts)
        spoken=guard_reply(SimpleNamespace(config={'operation_control':{'enabled':True}},_operation_control=control),raw) if label=='candidate' else raw
        item={'ttft_ms':round((first or 0)*1000),'first_tts_enqueue_ms':round(end*1000),
              'response':spoken,'native_calls':calls,'input_usage':provider.last_usage,'order':len(pair)+1}
        # Same official TTS first-audio check on two fixed pairs, not a second LLM.
        if idx in (0,4):
            tts_cfg=model_config('TTS_QwenAudioTTSPlus')
            audio,first_audio=asyncio.run(synthesize(tts_cfg,caption_from(spoken)))
            item['tts_first_audio_ms']=first_audio;item['user_to_first_audio_ms']=round(end*1000)+first_audio
        pair[label]=item
    rows.append({'text':text,'pair':pair})
    (OUT/'latency-acceptance.json').write_text(json.dumps({'cases':rows},ensure_ascii=False,indent=2))
def p95(values):return sorted(values)[max(0,__import__('math').ceil(.95*len(values))-1)]
summary={}
for label in ('baseline','candidate'):
    for metric in ('ttft_ms','first_tts_enqueue_ms'):
        vals=[r['pair'][label][metric] for r in rows]
        summary[label+'_'+metric]={'p50':statistics.median(vals),'p95':p95(vals)}
summary['p95_enqueue_delta_ms']=summary['candidate_first_tts_enqueue_ms']['p95']-summary['baseline_first_tts_enqueue_ms']['p95']
summary['provisional_latency_gate_pass']=summary['p95_enqueue_delta_ms']<=300
summary['sample_limitation']='12 paired chat cases; TTS audio timing for 2 pairs; not a population guarantee'
(OUT/'latency-acceptance.json').write_text(json.dumps({'summary':summary,'cases':rows,'model_calls':24,'maximum_calls':30},ensure_ascii=False,indent=2))
print(json.dumps(summary),flush=True)
