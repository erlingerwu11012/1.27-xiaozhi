"""Opt-in synthetic hardware tests. Keys stay in memory; no customer content.

Uses a dedicated temporary gateway wallet, never Aimi. Response usage is saved
without estimates. Audio remains in memory and is discarded after ASR.
"""
import asyncio, base64, json, secrets, subprocess, time, uuid, struct, zlib, inspect
from pathlib import Path
import httpx, websockets

ROOT=Path('/root/prjs/tmp/hardware-billing70-20261001')
MYSQL=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c',
       'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(q):return subprocess.run(MYSQL,input=q,text=True,capture_output=True,check=True).stdout.strip()
rows=[]
RUN=uuid.uuid4().hex[:12]
HEADER_ARG='additional_headers' if 'additional_headers' in inspect.signature(websockets.connect).parameters else 'extra_headers'
def record(name,passed,**values):
    item={'run_id':RUN,'case':name,'passed':bool(passed),**values};rows.append(item)
    with (ROOT/'tests/real-model-receipts.jsonl').open('a') as stream:stream.write(json.dumps(item)+'\n')
    (ROOT/'tests/real-models.json').write_text(json.dumps({'synthetic_only':True,'production_release':False,'cases':rows},indent=2))
    print(json.dumps(item),flush=True)

async def tts(token):
    ident=str(uuid.uuid4());audio=bytearray();usage=None;request_id=None
    async with websockets.connect('ws://127.0.0.1:3011/bailian/api-ws/v1/inference',**{HEADER_ARG:{'Authorization':'Bearer sk-'+token}},open_timeout=15) as ws:
        await ws.send(json.dumps({'header':{'action':'run-task','task_id':ident,'streaming':'duplex'},'payload':{'task_group':'audio','task':'tts','function':'SpeechSynthesizer','model':'qwen-audio-3.0-tts-plus','parameters':{'text_type':'PlainText','voice':'longanlingxi','format':'pcm','sample_rate':16000,'volume':50,'rate':1,'pitch':1},'input':{}}}))
        while True:
            raw=await asyncio.wait_for(ws.recv(),30)
            if isinstance(raw,bytes):audio.extend(raw);continue
            msg=json.loads(raw);event=msg.get('header',{}).get('event');request_id=msg.get('header',{}).get('task_id') or request_id
            if event=='task-started':
                await ws.send(json.dumps({'header':{'action':'continue-task','task_id':ident,'streaming':'duplex'},'payload':{'input':{'text':'测试用语，请把音量调到百分之三十。'}}},ensure_ascii=False))
                await ws.send(json.dumps({'header':{'action':'finish-task','task_id':ident,'streaming':'duplex'},'payload':{'input':{}}}))
            if msg.get('payload',{}).get('usage') is not None:usage=msg['payload']['usage']
            if event=='task-failed':raise RuntimeError('tts_task_failed')
            if event=='task-finished':break
    record('tts-real',len(audio)>0,model='qwen-audio-3.0-tts-plus',audio_bytes=len(audio),usage=usage,upstream_request_id=request_id)
    return bytes(audio)

async def asr(token,audio):
    text='';usage=None;request_id=None
    async with websockets.connect('ws://127.0.0.1:3001/v1/realtime?model=qwen3-asr-flash-realtime',**{HEADER_ARG:{'Authorization':'Bearer sk-'+token}},open_timeout=15) as ws:
        while True:
            msg=json.loads(await asyncio.wait_for(ws.recv(),30));kind=msg.get('type')
            if kind=='session.created':
                request_id=msg.get('session',{}).get('id')
                await ws.send(json.dumps({'event_id':'test-config','type':'session.update','session':{'modalities':['text'],'input_audio_format':'pcm','sample_rate':16000,'turn_detection':None,'input_audio_transcription':{'language':'zh'}}}))
            if kind=='session.updated':
                for offset in range(0,len(audio),3200):
                    await ws.send(json.dumps({'type':'input_audio_buffer.append','audio':base64.b64encode(audio[offset:offset+3200]).decode()}))
                    # Match real 16 kHz PCM pacing; do not trigger ingress burst protection.
                    await asyncio.sleep(.1)
                await ws.send(json.dumps({'type':'input_audio_buffer.commit'}))
            if kind=='conversation.item.input_audio_transcription.completed':
                text=msg.get('transcript','');usage=msg.get('usage',usage)
                await ws.send(json.dumps({'type':'session.finish'}))
            if msg.get('usage') is not None:usage=msg['usage']
            if kind=='error':
                code=(msg.get('error') or {}).get('code')
                record('asr-error-code',False,code=code)
                raise RuntimeError('asr_upstream_error')
            if kind=='session.finished':break
    record('asr-real','音量' in text and ('三十' in text or '30' in text),model='qwen3-asr-flash-realtime',recognized_chars=len(text),usage=usage,upstream_request_id=request_id)

async def main():
    name='codex-hardware70-'+secrets.token_hex(6);token=secrets.token_hex(24);owner=None
    # Limited isolated test wallet. No actual customer balance or binding changes.
    sql("INSERT INTO one_api.users(username,password,display_name,role,status,quota,used_quota,request_count,`group`,access_token,aff_code) VALUES('"+name+"','"+secrets.token_hex(32)+"','synthetic-hardware70',1,1,1000000,0,0,'default','"+secrets.token_hex(16)+"','"+secrets.token_hex(4)+"');")
    owner=int(sql("SELECT id FROM one_api.users WHERE username='"+name+"';"))
    try:
        sql("INSERT INTO one_api.tokens(user_id,`key`,status,name,created_time,accessed_time,expired_time,remain_quota,unlimited_quota,used_quota,models,subnet) VALUES("+str(owner)+",'"+token+"',1,'synthetic-hardware70',"+str(int(time.time()))+","+str(int(time.time()))+",-1,1000000,0,0,'qwen-plus,qwen3-vl-flash,qwen3-asr-flash-realtime,qwen-audio-3.0-tts-plus','');")
        async with httpx.AsyncClient(timeout=45) as client:
            cases=[('main','简单回答：一加一等于几？'),('summary','将下列虚构对话概括为事实和待办：用户说我喜欢绿茶，周五提醒我买茶。助手说好的。不要新增事实。'),('habit','基于合成行为：周一至周五每天七点读书，周末没有记录。只返回JSON：habit,repeat_days。不实际创建提醒。')]
            for case,content in cases:
                response=await client.post('http://127.0.0.1:3000/v1/chat/completions',headers={'Authorization':'Bearer sk-'+token},json={'model':'qwen-plus','messages':[{'role':'user','content':content}],'max_tokens':180,'temperature':0,'enable_thinking':False})
                if response.status_code!=200:record(case+'-real',False,status=response.status_code);continue
                payload=response.json();answer=payload.get('choices',[{}])[0].get('message',{}).get('content','')
                record(case+'-real',bool(answer),model='qwen-plus',usage=payload.get('usage'),upstream_request_id=payload.get('id'))
            def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
            png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',128,128,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xff\0\0'*128)*128))+chunk(b'IEND',b'')
            response=await client.post('http://127.0.0.1:3000/v1/chat/completions',headers={'Authorization':'Bearer sk-'+token},json={'model':'qwen3-vl-flash','messages':[{'role':'user','content':[{'type':'text','text':'这张图是什么颜色？只说颜色。'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(png).decode()}}]}],'max_tokens':40,'temperature':0,'enable_thinking':False})
            if response.status_code!=200:record('vision-real',False,status=response.status_code)
            else:
                payload=response.json();answer=payload.get('choices',[{}])[0].get('message',{}).get('content','')
                record('vision-real','红' in answer,model='qwen3-vl-flash',usage=payload.get('usage'),upstream_request_id=payload.get('id'))
        try:audio=await tts(token)
        except Exception as exc:record('tts-real',False,error_type=type(exc).__name__);audio=None
        if audio:
            try:await asr(token,audio)
            except Exception as exc:record('asr-real',False,error_type=type(exc).__name__)
        used=sql('SELECT used_quota FROM one_api.users WHERE id='+str(owner)+';')
        (ROOT/'tests/real-wallet.json').write_text(json.dumps({'test_owner':owner,'legacy_gateway_quota':int(used),'new_billing_end_to_end':False}))
    finally:
        if owner:
            # Keep non-sensitive receipt aggregates, then remove only our rows.
            sql("DELETE FROM one_api.logs WHERE user_id="+str(owner)+"; DELETE FROM one_api.tokens WHERE user_id="+str(owner)+" AND name='synthetic-hardware70'; DELETE FROM one_api.users WHERE id="+str(owner)+" AND username='"+name+"';")
    return 0 if rows and all(x['passed'] for x in rows) else 1

if __name__=='__main__':raise SystemExit(asyncio.run(main()))
