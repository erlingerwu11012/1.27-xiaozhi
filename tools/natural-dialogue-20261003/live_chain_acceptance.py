"""Bounded live read-only MCP, native streaming and synthetic-audio acceptance.

No hardware writes or customer conversation history. Credentials stay in memory.
Synthetic TTS recordings do not substitute for physical microphone acceptance.
"""
import asyncio, json, os, re, subprocess, sys, time, uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.request import Request, urlopen
import yaml

PROD=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
ROOT=Path('/root/prjs/tmp/natural-dialogue-20261003/main/xiaozhi-server')
OUT=ROOT.parents[1]
os.chdir(ROOT);sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'test'))
import config.logger
config.logger.setup_logging=lambda:MagicMock()
db=yaml.safe_load((PROD.parent/'manager-api/src/main/resources/application-dev.yml').read_text())['spring']['datasource']['druid']
m=re.search(r'mysql://([^:/]+)(?::(\d+))?/([^?]+)',db['url'])
env=dict(os.environ,MYSQL_PWD=str(db['password']))
def sql(query):
    return subprocess.run(['mysql','--host='+m[1],'--port='+(m[2]or'3306'),'--user='+str(db['username']),
        '--batch','--raw','--skip-column-names',m[3],'-e',query],env=env,capture_output=True,text=True,check=True,timeout=15).stdout.strip()
def model_config(ident):
    assert re.fullmatch(r'[A-Za-z0-9_]+',ident)
    return json.loads(sql("SELECT config_json FROM ai_model_config WHERE id='"+ident+"';"))
mgr=yaml.safe_load((PROD/'data/.config.yaml').read_text())['manager-api']
url=mgr['url'].rstrip('/')
if '/xiaozhi' not in url:url+='/xiaozhi'
with urlopen(Request(url+'/config/server-base',data=b'{}',headers={'Authorization':'Bearer '+mgr['secret'],'Content-Type':'application/json'}),timeout=15) as r:
    base=json.load(r)['data']
llm=model_config('LLM_QwenPlusOfficial')
key=str(llm['api_key']).removeprefix('sk-');assert re.fullmatch('[A-Za-z0-9_-]+',key)
owner=int(sql("SELECT user_id FROM one_api.tokens WHERE `key`='"+key+"' LIMIT 1;"))
def quota():return int(sql('SELECT used_quota FROM one_api.users WHERE id='+str(owner)+';'))
start_quota=quota()
def check_budget():assert quota()-start_quota<1200000,'shared_quota_guard'
from core.utils.prompt_manager import PromptManager
PERSONA='你腹黑、调皮、爱捉弄人。说话带一点坏心眼，喜欢调侃用户，但本质是善意的玩笑。'
prompt=PromptManager({'system_base_prompt':base.get('system_base_prompt',''),'language':'中文'},logger=MagicMock()).build_enhanced_prompt_v2(PERSONA,'synthetic-live',device_name='小智',user_nickname='主人',official_enhanced=True)
report={'hardware_actions':0,'recording_source':'synthetic official TTS; real ASR provider; no physical microphone',
        'voice':[],'native_mcp':[],'model_calls':0,'maximum_model_calls':12,'maximum_tts_calls':20,'maximum_asr_sessions':20,
        'maximum_shared_quota':1200000}

async def mcp_test():
    from core.providers.tools.server_mcp.mcp_client import ServerMCPClient
    from core.providers.llm.openai.openai import LLMProvider
    settings=json.loads((PROD/'data/.mcp_server_settings.json').read_text())['mcpServers']
    client=ServerMCPClient(next(c for c in settings.values() if not c.get('disabled',False)))
    provider=LLMProvider(dict(llm,timeout=35,max_tokens=200))
    provider.client=provider.client.with_options(max_retries=0)
    try:
        await asyncio.wait_for(client.initialize(),20)
        tools=client.get_available_tools()
        for question in ['请查询东京现在的时间','请查询伦敦现在的时间','请查询上海现在的时间']:
            check_budget();assert report['model_calls']+2<=12
            messages=[{'role':'system','content':prompt},{'role':'user','content':question}]
            def stream(dialogue):
                calls={};parts=[];ttft=None;begin=time.perf_counter();report['model_calls']+=1
                for text, chunks in provider.response_with_functions('synthetic-live',dialogue,functions=tools,max_tokens=200):
                    if ttft is None and (text or chunks):ttft=time.perf_counter()-begin
                    if text:parts.append(text)
                    for c in chunks or []:
                        row=calls.setdefault(c.index,{'id':'','name':'','arguments':''})
                        if c.id:row['id']=c.id
                        if c.function.name:row['name']+=c.function.name
                        if c.function.arguments:row['arguments']+=c.function.arguments
                return {'text':''.join(parts),'calls':list(calls.values()),'ttft_ms':round((ttft or 0)*1000),'elapsed_ms':round((time.perf_counter()-begin)*1000)}
            first=await asyncio.to_thread(stream,messages)
            item={'question':question,'first':first,'success':False}
            if len(first['calls'])==1 and first['calls'][0]['name']=='get_world_time':
                call=first['calls'][0];args=json.loads(call['arguments'])
                result=await asyncio.wait_for(client.call_tool(call['name'],args),15)
                receipt=result.model_dump(mode='json')
                messages.append({'role':'assistant','content':first['text'] or None,'tool_calls':[{'id':call['id'],'type':'function','function':{'name':call['name'],'arguments':call['arguments']}}]})
                messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(receipt,ensure_ascii=False)})
                final=await asyncio.to_thread(stream,messages)
                item.update(receipt=receipt,final=final,success=not receipt.get('isError',False) and not final['calls'] and bool(final['text']))
            report['native_mcp'].append(item)
    finally:await client.cleanup()

SAMPLES=[
    '把音量调到三十','请把声音设置为二十','把屏幕亮度调到八十','把音量调低十格',
    '打开摄像头预览','关闭摄像头','拍一张照片，看看桌上有什么','查询设备当前状态',
    '两分钟后提醒我喝水','明天上午九点提醒我开会','帮我记个便签，出门带伞',
    '不要打开摄像头','不用拍照','音量是什么','如果打开摄像头会怎样',
    '提醒我喝水','明天上午十点','算了','你好，我们正常聊一会儿','二十三乘以十七等于多少']
async def synthesize(cfg,text):
    import websockets
    from core.providers.tts.official.params import build_run_task,build_continue_task,build_finish_task
    from core.utils.hardware_billing import websocket_headers
    task=str(uuid.uuid4());token=str(cfg['api_key']);token=token if token.startswith('sk-') else 'sk-'+token
    endpoint=cfg.get('ws_url') or 'ws://127.0.0.1:3011/bailian/api-ws/v1/inference'
    snapshot=dict(cfg,format='pcm',sample_rate=16000,voice='longanlingxi',rate=1.0,volume=50)
    pcm=[];sent=False;begin=time.perf_counter();first=None
    async with websockets.connect(endpoint,additional_headers=websocket_headers(endpoint,cfg,{'Authorization':'Bearer '+token}),max_size=10*1024*1024,close_timeout=3) as ws:
        await ws.send(json.dumps(build_run_task(task,snapshot)))
        while True:
            chunk=await asyncio.wait_for(ws.recv(),20)
            if isinstance(chunk,bytes):
                if first is None:first=time.perf_counter()-begin
                pcm.append(chunk);continue
            msg=json.loads(chunk);event=msg.get('header',{}).get('event')
            if event=='task-started' and not sent:
                sent=True
                await ws.send(json.dumps(build_continue_task(task,text),ensure_ascii=False))
                await ws.send(json.dumps(build_finish_task(task)))
            if event=='task-failed':raise RuntimeError('tts_task_failed')
            if event=='task-finished':break
    data=b''.join(pcm);assert data,'tts_empty_audio'
    return data,round((first or 0)*1000)

async def voice_test():
    asr_id=base['selected_module']['ASR'];tts_id='TTS_QwenAudioTTSPlus'
    asr_cfg=model_config(asr_id);tts_cfg=model_config(tts_id)
    report['providers']={'asr_id':asr_id,'tts_id':tts_id,'asr_model':asr_cfg.get('model_name'),'tts_model':tts_cfg.get('model')}
    # FakeConn only supplies session state; the production provider contacts the
    # real upstream. Override final delivery to avoid all customer/device writes.
    from test_qwen3_asr_realtime import FakeConn
    from core.providers.asr.qwen3_asr_realtime import ASRProvider
    from core.utils.operation_control import OperationControl
    from core.utils.utterance_state import request_stop
    for idx,text in enumerate(SAMPLES):
        check_budget();item={'id':idx+1,'spoken_text':text}
        provider=None
        try:
            audio,first=await asyncio.wait_for(synthesize(tts_cfg,text),40)
            item.update(audio_ms=round(len(audio)/32),tts_first_audio_ms=first)
            conn=FakeConn(asyncio.get_running_loop());conn.session_id='synthetic-audio-'+str(idx)
            provider=ASRProvider(asr_cfg,True);done=asyncio.Future()
            async def capture(c,frames,final_text=None,**kw):
                if not done.done():done.set_result(final_text)
            provider.handle_voice_stop=capture
            await provider.open_audio_channels(conn)
            await provider.receive_audio(conn,audio[:1920],True)
            for _ in range(150):
                if provider._current and provider._current.state=='RUNNING':break
                await asyncio.sleep(.05)
            assert provider._current and provider._current.state=='RUNNING','asr_not_ready'
            for off in range(1920,len(audio),1920):
                await provider.receive_audio(conn,audio[off:off+1920],True)
                await asyncio.sleep(.06)
            begin=time.perf_counter();request_stop(conn,'device_stop')
            await provider.stop_listening(conn)
            transcript=await asyncio.wait_for(done,15)
            item.update(asr_text=transcript,asr_final_after_stop_ms=round((time.perf_counter()-begin)*1000))
            expected=OperationControl().begin(text,('s','p'));actual=OperationControl().begin(transcript,('s','p'))
            def sig(plan):return {'requests':[{'kind':r.kind,'arguments':r.arguments,'delta':r.delta} for r in plan.requests],'reply':plan.reply}
            # Chinese/Arabic numbers and punctuation may differ; compare meaning
            # with normalization, retaining every real transcript for review.
            def meaning(plan):
                rows=[]
                for r in plan.requests:
                    args=dict(r.arguments)
                    for k in ('text','question'):
                        if k in args:args[k]=re.sub(r'[，,。.!！?？\s]','',str(args[k]))
                    rows.append((r.kind,args,r.delta))
                return rows,plan.reply
            item.update(expected_plan=sig(expected),actual_plan=sig(actual),contract_match=meaning(expected)==meaning(actual),success=bool(transcript))
        except Exception as exc:item.update(success=False,error_type=type(exc).__name__,error_code=str(exc) if re.fullmatch(r'[a-z_]+',str(exc)) else 'see_redacted_failure')
        finally:
            if provider:await provider.close()
        report['voice'].append(item)
        (OUT/'live-chain-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps({'voice_case':idx+1,'success':item['success'],'contract_match':item.get('contract_match'),'error':item.get('error_code')},ensure_ascii=False),flush=True)

async def main():
    if '--inspect' in sys.argv:
        print(json.dumps({'selected':base['selected_module'],'tts_ids':sql("SELECT id FROM ai_model_config WHERE id LIKE 'TTS_%';").splitlines(),'asr_keys':list(model_config(base['selected_module']['ASR']))}));return
    await mcp_test();await voice_test()
    report['summary']={'mcp_pass':sum(c['success'] for c in report['native_mcp']),'mcp_cases':len(report['native_mcp']),
        'voice_recognized':sum(c['success'] for c in report['voice']),'voice_cases':len(report['voice']),
        'voice_contract_matches':sum(c.get('contract_match',False) for c in report['voice'])}
    (OUT/'live-chain-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report['summary']),flush=True)
if __name__=='__main__':asyncio.run(main())
