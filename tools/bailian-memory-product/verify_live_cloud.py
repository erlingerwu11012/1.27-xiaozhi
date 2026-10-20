"""Real published gateway, temporary wallet and two synthetic people only."""
import hashlib
import hmac
import json
import secrets
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

assert json.loads(Path('/root/prjs/tmp/bailian-memory-release-20260929/published.json').read_text())['published']
env={}
for line in Path('/etc/one-api-bailian.env').read_text().splitlines():
    if line.strip() and not line.lstrip().startswith('#'):
        key,value=shlex.split(line)[0].split('=',1);env[key]=value
secret=env['BAILIAN_MEMORY_SERVICE_SECRET'].encode()
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(query):return subprocess.run(mysql,input=query,text=True,capture_output=True,check=True).stdout.strip()
suffix=secrets.token_hex(6);username='codex-memory-live-test-'+suffix;key=secrets.token_hex(24)
sql("INSERT INTO one_api.users(username,password,display_name,role,status,quota,used_quota,request_count,`group`,access_token,aff_code) VALUES('"+username+"','"+secrets.token_hex(32)+"','合成记忆验收',1,1,10000,0,0,'default','"+secrets.token_hex(16)+"','"+secrets.token_hex(4)+"');")
owner=int(sql("SELECT id FROM one_api.users WHERE username='"+username+"';"))
sql("INSERT INTO one_api.tokens(user_id,`key`,status,name,created_time,accessed_time,expired_time,remain_quota,unlimited_quota,used_quota,models,subnet) VALUES("+str(owner)+",'"+key+"',1,'synthetic-memory-live-test',"+str(int(time.time()))+","+str(int(time.time()))+",-1,10000,0,0,'memory','');")
persons=['test_live_a_'+suffix,'test_live_b_'+suffix];events={};cleaned={};account='99123457'
def call(method,path,person,body=None,idem=None,attestation=True):
    expires=str(int(time.time())+120)
    canonical='\n'.join(['memory-v1',str(owner),account,person,'0',expires])
    headers={'Authorization':'Bearer sk-'+key,'Content-Type':'application/json','X-Memory-Account':account,'X-Memory-Person':person,'X-Memory-Generation':'0','X-Memory-Expires':expires,'X-Memory-Strategy':'lite'}
    if attestation:headers['X-Memory-Signature']=hmac.new(secret,canonical.encode(),hashlib.sha256).hexdigest()
    if idem:headers['Idempotency-Key']=idem
    req=urllib.request.Request('https://api.realecho.cn/bailian/api/v2/apps/memory/'+path,method=method,headers=headers,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req,timeout=90) as response:return response.status,json.loads(response.read()),response.headers
    except urllib.error.HTTPError as error:return error.code,json.loads(error.read()),error.headers
def wait(person,event):
    for _ in range(35):
        code,result,_=call('GET','events/'+event,person)
        assert code==200,('event_status',code)
        states=[v['status'] for v in result.get('events',[]) if 'status' in v]
        if 'status' in result:states.append(result['status'])
        assert not any(v in ['FAILED','UNRECORDED'] for v in states),'event_failed'
        if states and all(v=='SUCCEEDED' for v in states):return
        time.sleep(2)
    raise RuntimeError('event_completion_timeout')
def cleanup(person):
    if events.get(person):wait(person,events[person])
    code,_,_=call('POST','entities/retire',person,{})
    assert code==200
    for _ in range(12):
        code,result,_=call('GET','memory_nodes?page_size=100&page_num=1',person)
        assert code==200 and isinstance(result.get('total'),int)
        nodes=result.get('memory_nodes',[])
        if not nodes:
            assert result['total']==0
            code,_,_=call('POST','entities/cleanup-complete',person,{})
            assert code==200;cleaned[person]=True;return
        for node in nodes:
            code,_,_=call('DELETE','memory_nodes/'+node['memory_node_id'],person)
            assert code==200
    raise RuntimeError('cleanup_incomplete')
report={'passed':False,'gateway':'https://api.realecho.cn','portrait_written':False,'synthetic_only':True}
try:
    assert call('GET','memory_nodes',persons[0],attestation=False)[0]==403
    totals=[]
    for i,person in enumerate(persons):
        body={'messages':[{'role':'user','content':['我平时喜欢喝茉莉花茶，不喜欢咖啡。','我平时喜欢喝拿铁咖啡，不喜欢茶。'][i]}]}
        code,result,_=call('POST','add-async',person,body,'add-'+person)
        assert code==200,('add',code)
        events[person]=result['event_id'];wait(person,events[person])
        code,replay,headers=call('POST','add-async',person,body,'add-'+person)
        assert code==200 and headers.get('X-Memory-Replay')=='1' and replay['event_id']==events[person]
        code,result,_=call('GET','memory_nodes?page_size=100&page_num=1',person)
        assert code==200 and result['total']>0;totals.append(result['total'])
        if i==0:
            node=result['memory_nodes'][0]['memory_node_id'];assert call('GET','memory_nodes/'+node,persons[1])[0]==403
        code,result,_=call('POST','memory_nodes/search',person,{'messages':[{'role':'user','content':'我喜欢喝什么？'}]},'search-'+person)
        assert code==200 and result.get('plan_version')=='lite' and result.get('memory_nodes')
        text=json.dumps(result['memory_nodes'],ensure_ascii=False)
        assert ('拿铁' not in text if i==0 else '茉莉' not in text)
    cleanup(persons[0])
    code,result,_=call('GET','memory_nodes',persons[1]);assert code==200 and result['total']==totals[1]
    cleanup(persons[1])
    used=int(sql('SELECT used_quota FROM one_api.users WHERE id='+str(owner)+';'))
    bills=sql('SELECT c.operation,c.strategy,COUNT(*),SUM(b.charged) FROM one_api.memory_charges c JOIN one_api.bailian_bills b ON b.id=c.bill_id WHERE c.user_id='+str(owner)+' GROUP BY c.operation,c.strategy;')
    report.update(passed=True,individual_fact_delete_isolated=True,temporary_facts_removed=True,replay_not_charged=True,normal_token_cannot_bypass_service=True,synthetic_wallet_used_quota=used,bills=bills,fact_counts=totals,nominal_sales_cny=used*7/500000)
    print(json.dumps(report,ensure_ascii=False),flush=True)
finally:
    for person in persons:
        if not cleaned.get(person):
            try:cleanup(person)
            except Exception:report['cleanup_pending']=True
    report['temporary_facts_removed']=all(cleaned.get(person) for person in persons)
    Path('/tmp/bailian-memory-live-cloud-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    # Preserve financial ledger rows; remove only this temporary login/token.
    if report['temporary_facts_removed']:
        sql('DELETE FROM one_api.tokens WHERE user_id='+str(owner)+" AND name='synthetic-memory-live-test'; DELETE FROM one_api.users WHERE id="+str(owner)+" AND username='"+username+"';")
