"""Formal-domain smoke using a labelled synthetic wallet only; no customer data."""
from pathlib import Path
from fractions import Fraction
import json,subprocess,time,secrets,hashlib,hmac,urllib.request,urllib.error,base64,struct,zlib,asyncio,inspect,uuid
ROOT=Path('/root/prjs/tmp/hardware-billing70-20261001')
MYSQL=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(q):return subprocess.run(MYSQL,input=q,text=True,capture_output=True,check=True).stdout.strip()
config={}
for line in Path('/root/prjs/xiaozhi-esp32-server/secrets/hardware-billing70.env').read_text().splitlines():
    k,v=line.removeprefix('export ').split('=',1);config[k]=v
signing=config['HW_BILLING_SERVICE_KEY'].encode()
run=secrets.token_hex(6);account='990'+str(int(run,16));name='synthetic-hardware70-publish-'+run;token=secrets.token_hex(24)
now=int(time.time());rows=[];owner=None
def post(payload,operation,ident,account_override=None,proof=True):
    raw=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode();path='/v1/chat/completions';ts=str(int(time.time()));acct=account_override or account
    hdr={'Authorization':'Bearer sk-'+token,'Content-Type':'application/json'}
    if proof:
        signed='\n'.join(['POST',path,hashlib.sha256(raw).hexdigest(),ts,ident,acct,operation]).encode()
        hdr.update({'X-HW-Account':acct,'X-HW-Operation':operation,'X-HW-Request-ID':ident,'X-HW-Timestamp':ts,'X-HW-Signature':hmac.new(signing,signed,hashlib.sha256).hexdigest()})
    req=urllib.request.Request('https://api.realecho.cn'+path,data=raw,headers=hdr)
    try:
        with urllib.request.urlopen(req,timeout=45) as response:return response.status,json.load(response)
    except urllib.error.HTTPError as e:return e.code,{}
def call(payload,operation,label):
    ident='publish-smoke-'+run+'-'+label
    status,body=post(payload,operation,ident)
    if status!=200:raise RuntimeError('formal call failed '+label+' status '+str(status))
    data=sql('SELECT state,cost_cny,sale_cny,allocations,usage_json FROM one_api.hardware_billing_bill WHERE user_id='+str(owner)+' AND id=\''+ident+'\';').split('\t')
    state,cost,sale,alloc,meter=data;assert state=='settled'
    cost,sale=Fraction(cost),Fraction(sale);assert (sale-cost)/sale==Fraction(7,10)
    assert post(payload,operation,ident)[0]==403
    rows.append({'case':label,'state':state,'cost_cny_exact':str(cost),'sale_cny_exact':str(sale),'margin':'0.70','allocations':json.loads(alloc),'usage':json.loads(meter),'duplicate_rejected':True})
    return body

async def audio_smoke():
    import websockets
    header_arg='additional_headers' if 'additional_headers' in inspect.signature(websockets.connect).parameters else 'extra_headers'
    def connect(path,op,ident):
        ts=str(int(time.time()));signed='\n'.join(['GET',path,hashlib.sha256(b'').hexdigest(),ts,ident,account,op]).encode()
        hdr={'Authorization':'Bearer sk-'+token,'X-HW-Account':account,'X-HW-Operation':op,'X-HW-Request-ID':ident,'X-HW-Timestamp':ts,'X-HW-Signature':hmac.new(signing,signed,hashlib.sha256).hexdigest()}
        return websockets.connect('wss://api.realecho.cn'+path,**{header_arg:hdr},open_timeout=15)
    task=str(uuid.uuid4());pcm=bytearray();tts_id='publish-smoke-'+run+'-tts';asr_id='publish-smoke-'+run+'-asr'
    async with connect('/bailian/api-ws/v1/inference?model=qwen-audio-3.0-tts-plus','tts',tts_id) as ws:
        await ws.send(json.dumps({'header':{'action':'run-task','task_id':task,'streaming':'duplex'},'payload':{'task_group':'audio','task':'tts','function':'SpeechSynthesizer','model':'qwen-audio-3.0-tts-plus','parameters':{'text_type':'PlainText','voice':'longanlingxi','format':'pcm','sample_rate':16000,'volume':50,'rate':1,'pitch':1},'input':{}}}))
        while True:
            raw=await asyncio.wait_for(ws.recv(),35)
            if isinstance(raw,bytes):pcm.extend(raw);continue
            msg=json.loads(raw);event=msg.get('header',{}).get('event')
            if msg.get('type')=='error' or event=='task-failed':raise RuntimeError('formal synthetic TTS failed')
            if event=='task-started':
                await ws.send(json.dumps({'header':{'action':'continue-task','task_id':task,'streaming':'duplex'},'payload':{'input':{'text':'测试用语，请把音量调到百分之三十。'}}}))
                await ws.send(json.dumps({'header':{'action':'finish-task','task_id':task,'streaming':'duplex'},'payload':{'input':{}}}))
            if event=='task-finished':break
    assert pcm
    recognized=False
    async with connect('/bailian/api-ws/v1/realtime?model=qwen3-asr-flash-realtime','asr',asr_id) as ws:
        while True:
            msg=json.loads(await asyncio.wait_for(ws.recv(),35));kind=msg.get('type')
            if kind=='error':raise RuntimeError('formal synthetic ASR failed')
            if kind=='session.created':await ws.send(json.dumps({'type':'session.update','session':{'modalities':['text'],'input_audio_format':'pcm','sample_rate':16000,'turn_detection':None,'input_audio_transcription':{'language':'zh'}}}))
            if kind=='session.updated':
                for off in range(0,len(pcm),3200):
                    await ws.send(json.dumps({'type':'input_audio_buffer.append','audio':base64.b64encode(pcm[off:off+3200]).decode()}));await asyncio.sleep(.1)
                await ws.send(json.dumps({'type':'input_audio_buffer.commit'}))
            if kind=='conversation.item.input_audio_transcription.completed':
                text=msg.get('transcript','');recognized='音量' in text and ('三十' in text or '30' in text)
                await ws.send(json.dumps({'type':'session.finish'}))
            if kind=='session.finished':break
    pcm.clear();assert recognized
    for ident,label in [(tts_id,'tts'),(asr_id,'asr')]:
        for _ in range(50):
            data=sql(f"SELECT state,cost_cny,sale_cny,allocations,usage_json FROM one_api.hardware_billing_bill WHERE user_id={owner} AND id='{ident}';").split('\t')
            if data[0]=='settled':break
            await asyncio.sleep(.1)
        state,cost,sale,alloc,meter=data;assert state=='settled';cost,sale=Fraction(cost),Fraction(sale);assert (sale-cost)/sale==Fraction(7,10)
        rows.append({'case':label,'state':state,'cost_cny_exact':str(cost),'sale_cny_exact':str(sale),'margin':'0.70','allocations':json.loads(alloc),'usage':json.loads(meter),'synthetic_audio_not_saved':True})
try:
    sql("INSERT INTO one_api.users(username,password,display_name,role,status,quota,used_quota,request_count,`group`,access_token,aff_code) VALUES('"+name+"','"+secrets.token_hex(32)+"','synthetic-publish-test',1,1,0,0,0,'hardware70','"+secrets.token_hex(16)+"','"+secrets.token_hex(4)+"');")
    owner=int(sql("SELECT id FROM one_api.users WHERE username='"+name+"';"))
    sql("INSERT INTO one_api.tokens(user_id,`key`,status,name,created_time,accessed_time,expired_time,remain_quota,unlimited_quota,used_quota,models,subnet) VALUES("+str(owner)+",'"+token+"',1,'synthetic-publish-test',"+str(now)+","+str(now)+",-1,0,0,0,'qwen-plus,qwen3-vl-flash,qwen3-asr-flash-realtime,qwen-audio-3.0-tts-plus','');")
    sql(f"INSERT INTO one_api.hardware_billing_wallet(user_id,product_account,state,created_at) VALUES({owner},'{account}','enabled',{now}); INSERT INTO one_api.hardware_billing_lot(id,user_id,kind,remaining,cny_per_point,paid_cents,granted_points,original_points,created_at) VALUES('synthetic-publish:{run}',{owner},'paid','100','0.01',100,100,'100',{time.time_ns()});")
    def payload(text):return {'model':'qwen-plus','messages':[{'role':'user','content':text}],'max_tokens':100,'temperature':0,'enable_thinking':False}
    for op,text in [('llm','只回答数字：1加1是多少？'),('summary','概括虚构材料：用户爱喝绿茶，周五买茶。不得增添事实。'),('habit','只输出JSON：周一到周五每天七点读书，habit为读书，repeat_days为62。')]:
        result=call(payload(text),op,op);assert result.get('choices')
    def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',128,128,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xff\0\0'*128)*128))+chunk(b'IEND',b'')
    visual=payload('');visual['model']='qwen3-vl-flash';visual['messages']=[{'role':'user','content':[{'type':'text','text':'只说这张合成图片的颜色。'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(png).decode()}}]}]
    result=call(visual,'vision','vision');assert '红' in result['choices'][0]['message']['content']
    tool=payload('必须调用test_sum计算1加1。不要自行回答。');tool['tools']=[{'type':'function','function':{'name':'test_sum','description':'合成测试：计算两数之和，无设备操作。','parameters':{'type':'object','properties':{'a':{'type':'integer'},'b':{'type':'integer'}},'required':['a','b']}}}]
    result=call(tool,'llm','tool');msg=result['choices'][0]['message'];calls=msg.get('tool_calls');assert calls and calls[0]['function']['name']=='test_sum'
    follow=payload('');follow['messages']=[tool['messages'][0],msg,{'role':'tool','tool_call_id':calls[0]['id'],'content':'2'}]
    result=call(follow,'llm','tool-result');assert '2' in result['choices'][0]['message']['content'] or '二' in result['choices'][0]['message']['content']
    assert post(payload('不要执行'),'llm','no-proof',proof=False)[0]==403
    assert post(payload('不要执行'),'llm','foreign-proof',account_override='other-synthetic-account')[0]==403
    asyncio.run(audio_smoke())
    available=sum(Fraction(x) for x in sql(f'SELECT remaining FROM one_api.hardware_billing_lot WHERE user_id={owner};').splitlines())
    consumed=sum(Fraction(a['points']) for r in rows for a in r['allocations']);assert available==100-consumed
    assert sql(f'SELECT used_quota FROM one_api.users WHERE id={owner};')=='0'
    report={'passed':True,'formal_domain':'https://api.realecho.cn','synthetic_only':True,'cases':rows,'balance_matches_allocations':True,'customer_balance_changed_by_test':False,'missing_proof_rejected':True,'foreign_account_rejected':True,'upstream_cost_cny_exact':str(sum(Fraction(r['cost_cny_exact']) for r in rows)),'wallet_sale_cny_exact':str(sum(Fraction(r['sale_cny_exact']) for r in rows))}
    (ROOT/'tests/formal-domain-smoke.json').write_text(json.dumps(report,indent=2));print(json.dumps({'passed':True,'cases':len(rows),'cost_cny_exact':report['upstream_cost_cny_exact'],'sale_cny_exact':report['wallet_sale_cny_exact']}))
finally:
    if owner:
        # Keep financial evidence, archive only our explicitly labelled test user.
        sql(f"UPDATE one_api.hardware_billing_wallet SET state='test_archived' WHERE user_id={owner} AND product_account='{account}'; UPDATE one_api.tokens SET status=2 WHERE user_id={owner} AND name='synthetic-publish-test'; UPDATE one_api.users SET status=2 WHERE id={owner} AND username='{name}';")
