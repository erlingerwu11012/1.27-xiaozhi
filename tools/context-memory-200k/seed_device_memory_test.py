"""User-authorized synthetic conversation through the production material queue.

Only the selected default person is advanced. Keeps facts for the user's device
questions; does not reset the daily schedule, modify roles, or create a reminder.
"""
from pathlib import Path
import base64,hashlib,hmac,json,os,secrets,shlex,subprocess,sys,time,urllib.request,urllib.error
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from decimal import Decimal

root=Path('/root/prjs/tmp/memory-test-20260930');root.mkdir(exist_ok=True);os.chmod(root,0o700)
target=json.loads((root/'target.json').read_text())
account=int(target['account_id']);person=target['state']['default_user_id'];generation=int(target['state']['default_generation'])
assert target['device_id'].lower()=='ac:a7:04:fd:20:2c' and target['memory']=='Memory_bailian'
assert target['state']['mode']=='default' and not target['voice_members'],'explicit_member_selection_required'
def literal(value):return "CONVERT(X'"+str(value).encode().hex()+"' USING utf8mb4)"
scope='account_id='+str(account)+' AND user_id='+literal(person)+' AND generation='+str(generation)
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(query):
    result=subprocess.run(mysql,input=query,text=True,capture_output=True)
    if result.returncode:
        # Only schema errors are useful for this test; never echo SQL values.
        error=result.stderr.splitlines()[0] if result.stderr else 'database_error'
        raise RuntimeError(error)
    return result.stdout.strip()
pm=json.loads(subprocess.run(['pm2','jlist'],capture_output=True,text=True,check=True).stdout)
pid=next(p['pid'] for p in pm if p['name']=='manager-api')
env=dict(x.decode().split('=',1) for x in Path('/proc/'+str(pid)+'/environ').read_bytes().split(b'\0') if b'=' in x)
assert env.get('MEMORY_PRODUCT_ENABLED')=='true' and env.get('MEMORY_PORTRAIT_ENABLED')=='false'
service_secret=sql("SELECT param_value FROM xiaozhi_esp32_server.sys_params WHERE param_code='server.secret';")
def request(method,url,headers,body=None,timeout=95):
    req=urllib.request.Request(url,method=method,headers=headers,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:return response.status,json.loads(response.read())
    except urllib.error.HTTPError as error:return error.code,json.loads(error.read())
def manager(method,path,body=None,extra=None):
    headers={'Content-Type':'application/json','Authorization':'Bearer '+service_secret}
    if extra:headers.update(extra)
    code,result=request(method,'http://127.0.0.1:8002/xiaozhi/'+path,headers,body)
    assert code==200 and result.get('code')==0,('manager_request_failed',code,result.get('code'))
    return result.get('data')
state=manager('GET','user-identities/internal/state/'+str(account))
assert state['mode']=='default' and state['default_user_id']==person and int(state['default_generation'])==generation
assert int(state['directory_version'])==int(target['state']['directory_version'])
# Resolve only this verified device account's existing binding, using the same
# AES-GCM format as OneApiBindingService. Credentials stay in process memory.
# Production memory calls resolve this binding in Java, without the legacy
# external /internal/oneapi endpoint (which is guarded by web OAuth).
binding=json.loads(sql("SELECT JSON_OBJECT('owner',oneapi_user_id,'cipher',oneapi_token_key_cipher,'fingerprint',oneapi_token_key_fingerprint) FROM xiaozhi_esp32_server.sys_user_oneapi_binding WHERE sys_user_id="+str(account)+";"))
owner=int(binding['owner']);encrypted=base64.b64decode(binding['cipher'])
token=AESGCM(bytes.fromhex(env['ONEAPI_TOKEN_CIPHER_KEY'])).decrypt(encrypted[:12],encrypted[12:],None).decode()
assert hashlib.sha256(token.encode()).hexdigest()==binding['fingerprint'],'binding_fingerprint_mismatch'
token=token if token.startswith('sk-') else 'sk-'+token
gateway_env={}
for line in Path('/etc/one-api-bailian.env').read_text().splitlines():
    if line.strip() and not line.lstrip().startswith('#'):
        key,value=shlex.split(line)[0].split('=',1);gateway_env[key]=value
signature_secret=gateway_env['BAILIAN_MEMORY_SERVICE_SECRET'].encode()
cloud='re_'+hashlib.sha256(':'.join([str(owner),str(account),person,str(generation)]).encode()).hexdigest()[:60]
def gateway(method,path,body=None,idem=None):
    expiry=str(int(time.time())+120)
    canonical='\n'.join(['memory-v1',str(owner),str(account),person,str(generation),expiry])
    headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','X-Memory-Account':str(account),'X-Memory-Person':person,
        'X-Memory-Generation':str(generation),'X-Memory-Expires':expiry,'X-Memory-Signature':hmac.new(signature_secret,canonical.encode(),hashlib.sha256).hexdigest(),'X-Memory-Strategy':'lite'}
    if idem:headers['Idempotency-Key']=idem
    code,result=request(method,'http://127.0.0.1:3011/bailian/api/v2/apps/memory/'+path,headers,body)
    assert code==200,('gateway_request_failed',code)
    return result
def save(report):
    (root/'seed-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));os.chmod(root/'seed-result.json',0o600)
def actor_for(turn):
    return {'account_id':account,'person_id':person,'generation':generation,'directory_version':state['directory_version'],
        'device_id':target['device_id'],'agent_id':target['agent_id'],'status':'default','mode':'default',
        'turn_id':turn,'listen_epoch':1,'captured_at':int(time.time()*1000)}
def advance(mark):
    changed=sql("START TRANSACTION; SELECT account_id FROM xiaozhi_esp32_server.ai_account_identity_state WHERE account_id="+str(account)+" FOR UPDATE; UPDATE xiaozhi_esp32_server.ai_person_memory_entity e JOIN xiaozhi_esp32_server.ai_account_identity_state s ON s.account_id=e.account_id SET e.daily_watermark="+str(mark)+",e.daily_started_at=UTC_TIMESTAMP() WHERE e."+scope.replace(' AND user_id',' AND e.user_id').replace(' AND generation',' AND e.generation')+" AND e.state='active' AND s.mode='default' AND s.default_user_id=e.user_id AND s.default_generation=e.generation AND s.directory_version="+str(state['directory_version'])+" AND NOT EXISTS(SELECT 1 FROM xiaozhi_esp32_server.ai_identity_cleanup c WHERE c.account_id=e.account_id AND c.user_id=e.user_id AND c.generation=e.generation); SELECT ROW_COUNT(); COMMIT;")
    assert changed.splitlines()[-1]=='1','identity_changed_before_trigger'
public_fields={'device':target['device_id'],'identity_mode':'default','portrait_written':False,'schedule_changed':False}
mode=sys.argv[1]
if mode=='start':
    assert not (root/'seed-result.json').exists(),'test_already_started_use_wait_or_recall'
    assert int(sql('SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_person_material WHERE '+scope+';'))==0,'real_materials_already_present'
    assert int(sql("SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_memory_task WHERE "+scope+" AND state NOT IN('complete','cancelled');"))==0,'existing_task_in_progress'
    quota=int(sql('SELECT quota FROM one_api.users WHERE id='+str(owner)+';'));assert quota>=2000,'insufficient_test_balance'
    before=gateway('GET','memory_nodes?page_size=100&page_num=1')
    assert before.get('total')==0,'existing_facts_require_selective_test'
    run='memory_test_20260930_'+secrets.token_hex(5)
    content=[
        '我把书房里的测试小台灯取名为蓝松果，它放在书房书桌左边。',
        '我的测试饮品偏好是温的茉莉花茶，不加糖，也不要冰的。',
        '我把测试笔记本取名为银月亮。',
        '更正一下，测试笔记本现在改名叫小山雀，银月亮是旧名字，以后按小山雀来记。',
    ]
    report={**public_fields,'run_id':run,'started_at':time.strftime('%Y-%m-%d %H:%M:%S %z'),'conversation':content,'state':'preparing','baseline_fact_count':0,'owner_private':owner,'cloud_private':cloud}
    save(report)
    for index,text in enumerate(content):
        actor={'account_id':account,'person_id':person,'generation':generation,'directory_version':state['directory_version'],
            'device_id':target['device_id'],'agent_id':target['agent_id'],'status':'default','mode':'default',
            'turn_id':run+'_'+str(index),'listen_epoch':1,'captured_at':int(time.time()*1000)}
        manager('POST','person-memory/internal/material',{'actor':actor,'eventId':run+':user:'+str(index),'kind':'dialogue','content':text})
    mark=int(sql('SELECT MAX(id) FROM xiaozhi_esp32_server.ai_person_material WHERE '+scope+';'))
    assert int(sql('SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_person_material WHERE '+scope+';'))==4
    changed=sql("START TRANSACTION; SELECT account_id FROM xiaozhi_esp32_server.ai_account_identity_state WHERE account_id="+str(account)+" FOR UPDATE; UPDATE xiaozhi_esp32_server.ai_person_memory_entity e JOIN xiaozhi_esp32_server.ai_account_identity_state s ON s.account_id=e.account_id SET e.daily_watermark="+str(mark)+",e.daily_started_at=UTC_TIMESTAMP() WHERE e."+scope.replace(' AND user_id',' AND e.user_id').replace(' AND generation',' AND e.generation')+" AND e.state='active' AND s.mode='default' AND s.default_user_id=e.user_id AND s.default_generation=e.generation AND s.directory_version="+str(state['directory_version'])+" AND NOT EXISTS(SELECT 1 FROM xiaozhi_esp32_server.ai_identity_cleanup c WHERE c.account_id=e.account_id AND c.user_id=e.user_id AND c.generation=e.generation); SELECT ROW_COUNT(); COMMIT;")
    assert changed.splitlines()[-1]=='1','identity_changed_before_trigger'
    report.update(state='queued',watermark=mark);save(report)
    print(json.dumps({**public_fields,'state':'queued','materials':4,'conversation':content,'run_id':run},ensure_ascii=False),flush=True)
elif mode in ('wait','wait-correction'):
    report=json.loads((root/'seed-result.json').read_text());mark=int(report['correction_watermark' if mode=='wait-correction' else 'watermark']);last=None
    for _ in range(80):
        value=sql("SELECT JSON_OBJECT('state',state,'attempts',attempts,'last_error',last_error,'event_received',event_id IS NOT NULL) FROM xiaozhi_esp32_server.ai_memory_task WHERE "+scope+" AND watermark="+str(mark)+" AND kind='extract';")
        task=json.loads(value) if value else {'state':'not_built'}
        if task['state']!=last:print(json.dumps(task),flush=True);last=task['state']
        if task['state']=='complete':
            if mode=='wait-correction':report.update(correction_completed=True,correction_completed_at=time.strftime('%Y-%m-%d %H:%M:%S %z'),correction_task=task)
            else:report.update(state='complete',completed_at=time.strftime('%Y-%m-%d %H:%M:%S %z'),task=task)
            save(report);break
        if task['state'] in ('failed','cancelled','review','retry'):
            report.update(state=task['state'],task=task);save(report);raise RuntimeError('task_needs_check_no_resubmission')
        time.sleep(3)
    else:raise RuntimeError('task_completion_timeout_no_resubmission')
elif mode=='correct':
    report=json.loads((root/'seed-result.json').read_text());assert report['state']=='complete'
    assert not report.get('correction_requested'),'correction_already_requested_do_not_repeat'
    assert int(sql('SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_person_material WHERE '+scope+';'))==0,'new_real_materials_present'
    assert int(sql('SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_agent_chat_history WHERE account_id='+str(account)+' AND person_id='+literal(person)+' AND default_generation='+str(generation)+';'))==0,'real_archive_present_do_not_invalidate_for_test'
    report['initial_cloud_result']={k:report[k] for k in ('fact_count','extracted_facts','recall','service_recall')}
    report['same_batch_correction_passed']=False
    report['correction_requested']=True;save(report)
    manager('POST','person-memory/internal/override',{'actor':actor_for(report['run_id']+'_correct'),'action':'correct','match':'银月亮','replacement':'用户的测试笔记本现在取名为小山雀。'})
    immediate=manager('POST','person-memory/internal/search',{'actor':actor_for(report['run_id']+'_check_correct'),'query':'我的测试笔记本现在叫什么？'})
    assert '小山雀' in immediate['text'] and '银月亮' not in immediate['text'],'immediate_correction_failed'
    report['immediate_correction_text']=immediate['text'];save(report)
    sql("UPDATE xiaozhi_esp32_server.ai_memory_override SET state='ready' WHERE "+scope+" AND match_text="+literal('银月亮')+" AND state='pending';")
    for _ in range(30):
        remaining=int(sql("SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_memory_override WHERE "+scope+" AND match_text="+literal('银月亮')+" AND state<>'complete';"))
        if remaining==0:break
        time.sleep(3)
    else:raise RuntimeError('correction_sync_pending_do_not_repeat')
    mark=int(sql('SELECT MAX(id) FROM xiaozhi_esp32_server.ai_person_material WHERE '+scope+';'))
    assert int(sql('SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_person_material WHERE '+scope+';'))==1,'unexpected_materials_do_not_advance'
    advance(mark);report['correction_watermark']=mark;report['correction_sync_done']=True;save(report)
    print(json.dumps({'immediate_correction_text':immediate['text'],'old_cloud_fact_removed':True,'replacement_queued':True},ensure_ascii=False),flush=True)
elif mode=='recall':
    report=json.loads((root/'seed-result.json').read_text());assert report['state']=='complete'
    facts=gateway('GET','memory_nodes?page_size=100&page_num=1')
    report['fact_count']=facts['total']
    report['extracted_facts']=[{'content':n.get('content',n.get('custom_content',''))} for n in facts.get('memory_nodes',[])]
    # The baseline was zero and only these four synthetic turns were uploaded.
    questions=['我书房的测试小台灯叫什么，放在哪里？','我的测试饮品偏好是什么，温度和糖有什么要求？','我给测试笔记本改了名字，现在叫什么？']
    checks=[]
    revision='-corrected' if report.get('correction_completed') else ''
    for i,query in enumerate(questions):
        result=gateway('POST','memory_nodes/search',{'messages':[{'role':'user','content':query}],'top_k':5,'plan_version':'lite'},report['run_id']+'-recall'+revision+'-'+str(i))
        text='\n'.join(str(n.get('content',n.get('custom_content',''))) for n in result.get('memory_nodes',[]))
        checks.append({'query':query,'plan':result.get('plan_version'),'text':text})
    report['recall']=checks
    save(report)
    # Also exercise the production chat search endpoint with its real deadline.
    service_checks=[]
    for i,query in enumerate(questions):
        actor={'account_id':account,'person_id':person,'generation':generation,'directory_version':state['directory_version'],
            'device_id':target['device_id'],'agent_id':target['agent_id'],'status':'default','mode':'default',
            'turn_id':report['run_id']+'_service'+revision+'_'+str(i),'listen_epoch':1,'captured_at':int(time.time()*1000)}
        started=time.monotonic()
        code,result=request('POST','http://127.0.0.1:8002/xiaozhi/person-memory/internal/search',
            {'Content-Type':'application/json','Authorization':'Bearer '+service_secret},{'actor':actor,'query':query},timeout=5)
        service_checks.append({'query':query,'http_status':code,'code':result.get('code'),
            'text':(result.get('data') or {}).get('text',''),'elapsed_ms':round((time.monotonic()-started)*1000)})
    report['service_recall']=service_checks;save(report)
    charges=sql("SELECT c.operation,c.strategy,c.state,COUNT(*),SUM(b.charged) FROM one_api.memory_charges c LEFT JOIN one_api.bailian_bills b ON BINARY b.id=BINARY c.bill_id WHERE BINARY c.cloud_user_id=BINARY "+literal(cloud)+" GROUP BY c.operation,c.strategy,c.state;")
    report['charges']=charges;report['kept_for_device_questions']=True
    report['local_archive_seeded']=False;report['local_summary_seeded']=False
    if report.get('correction_completed'):
        text='\n'.join(n['content'] for n in report['extracted_facts'])
        report['corrected_cloud_fact_passed']='小山雀' in text and '银月亮' not in text
        report['corrected_chat_recall_passed']='小山雀' in service_checks[2]['text'] and '银月亮' not in service_checks[2]['text']
    save(report)
    print(json.dumps({k:v for k,v in report.items() if not k.endswith('_private')},ensure_ascii=False),flush=True)
elif mode=='status':
    report=json.loads((root/'seed-result.json').read_text())
    pending_materials=int(sql('SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_person_material WHERE '+scope+';'))
    pending_tasks=int(sql("SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_memory_task WHERE "+scope+" AND state NOT IN('complete','cancelled');"))
    pending_changes=int(sql("SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_memory_override WHERE "+scope+" AND state<>'complete';"))
    unbalanced=int(sql('SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_person_memory_entity WHERE '+scope+' AND daily_watermark<>processed_watermark;'))
    portraits=int(sql('SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_person_memory_entity WHERE '+scope+' AND portrait_written=TRUE;'))
    unsettled=int(sql("SELECT COUNT(*) FROM one_api.memory_charges WHERE BINARY cloud_user_id=BINARY "+literal(cloud)+" AND state NOT IN('settled','refunded');"))
    assert (pending_materials,pending_tasks,pending_changes,unbalanced,portraits,unsettled)==(0,0,0,0,0,0),'test_state_needs_followup'
    report['final_status']={'at':time.strftime('%Y-%m-%d %H:%M:%S %z'),'pending_materials':pending_materials,
        'pending_tasks':pending_tasks,'pending_corrections':pending_changes,'unbalanced_watermarks':unbalanced,
        'portraits':portraits,'unsettled_charges':unsettled,
        'pm2':{p['name']:p['pm2_env']['status'] for p in pm if p['name'] in ('manager-api','manager-web','voiceprint-api','xiaozhi-server')}}
    save(report)
    public={k:v for k,v in report.items() if not k.endswith('_private')}
    (root/'public-result.json').write_text(json.dumps(public,ensure_ascii=False,indent=2));os.chmod(root/'public-result.json',0o600)
    print(json.dumps(report['final_status'],ensure_ascii=False),flush=True)
else:raise ValueError('choose_start_wait_recall_correct_wait-correction_or_status')
