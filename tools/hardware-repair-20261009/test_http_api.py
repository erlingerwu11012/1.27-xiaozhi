import json,sys,time,requests,uuid,os,signal,subprocess
from pathlib import Path
S=Path(__file__).parent;sys.path.insert(0,str(S));from budget import Budget
b=Budget(S/'budget.sqlite3');base='http://127.0.0.1:18002/xiaozhi';headers={'Authorization':'Bearer '+(S/'api-test-secret').read_text()};e=json.loads((S/'private-test-env.json').read_text())
import pymysql
c=pymysql.connect(host='127.0.0.1',user='root',password=e['PERSON_MEMORY_TEST_PASSWORD'],database=e['PERSON_MEMORY_TEST_DATABASE'],autocommit=True)
records=[]
def call(name,path,payload=None,auth=True,method='POST'):
 b.reserve('case','http-api:'+name);r=requests.request(method,base+path,json=payload,headers=headers if auth else {},timeout=5);data=r.json();records.append({'name':name,'status':r.status_code,'result':data});(S/'http-api-partial.json').write_text(json.dumps(records,ensure_ascii=False,indent=2));return r,data
for i in range(50):
 try:
  r=requests.get(base+'/user-identities/internal/state/99003',headers=headers,timeout=1)
  if r.status_code==200 and r.json().get('code')==0:break
 except requests.RequestException:pass
 time.sleep(1)
r,d=call('missing_auth','/person-memory/internal/recent',{},False);assert r.status_code==401
r,d=call('state','/user-identities/internal/state/99003',method='GET');assert d['code']==0,d
state=d['data'];a={'account_id':'99003','person_id':state['default_user_id'],'generation':state['default_generation'],'directory_version':state['directory_version'],'mode':'default','status':'default','turn_id':uuid.uuid4().hex,'device_id':'test-device-http','agent_id':'agent_http','listen_epoch':1,'captured_at':int(time.time()*1000)}
with c.cursor() as q:
 q.execute("DELETE FROM ai_agent_chat_history WHERE account_id=99003")
 q.execute("DELETE FROM ai_memory_override WHERE account_id=99003")
 for text,turn in [('我喜欢咖啡','coffee'),('我的台灯叫银杏灯','lamp')]:
  q.execute("INSERT INTO ai_agent_chat_history(mac_address,agent_id,session_id,chat_type,content,account_id,person_id,identity_status,turn_id,event_id,directory_version,default_generation,recall_allowed,created_at) VALUES('test-device-http','agent_http','s',1,%s,99003,%s,'default',%s,%s,%s,%s,TRUE,NOW())",(text,a['person_id'],turn,uuid.uuid4().hex,a['directory_version'],a['generation']))
r,d=call('search_before','/person-memory/internal/recent',{'actor':a,'query':'我喝咖啡吗'});assert '我喜欢咖啡' in d['data']['text']
r,d=call('correct','/person-memory/internal/override',{'actor':a,'action':'correct','match':'我喜欢咖啡','replacement':'我现在不喝咖啡了'});assert d['data']['local_applied'] is True
r,d=call('search_after_correct','/person-memory/internal/recent',{'actor':a,'query':'我喝咖啡吗'});assert '我现在不喝咖啡了' in d['data']['text'] and '我喜欢咖啡' not in d['data']['text']
r,d=call('unrelated_preserved','/person-memory/internal/recent',{'actor':a,'query':'我的台灯叫什么'});assert '银杏灯' in d['data']['text']
r,d=call('foreign_device','/person-memory/internal/override',{'actor':{**a,'device_id':'test-device-b'},'action':'forget','match':'我的台灯叫银杏灯'});assert d['code']!=0
r,d=call('forget','/person-memory/internal/override',{'actor':a,'action':'forget','match':'我的台灯叫银杏灯'});assert d['data']['local_applied'] is True
r,d=call('after_forget','/person-memory/internal/recent',{'actor':a,'query':'台灯'});assert '银杏灯' not in d['data']['text']
pid=json.loads((S/'candidate-manager-pid.json').read_text())['pid'];os.kill(pid,signal.SIGTERM)
import socket
for _ in range(60):
 with socket.socket() as sock:
  if sock.connect_ex(('127.0.0.1',18002))!=0:break
 time.sleep(.5)
else:raise RuntimeError('isolated_api_did_not_stop')
subprocess.run([sys.executable,str(S/'start_api.py')],check=True,stdout=subprocess.DEVNULL)
for i in range(50):
 try:
  r=requests.get(base+'/user-identities/internal/state/99003',headers=headers,timeout=1)
  if r.status_code==200 and r.json().get('code')==0:break
 except requests.RequestException:pass
 time.sleep(1)
r,d=call('correct_persists_restart','/person-memory/internal/recent',{'actor':a,'query':'我喝咖啡吗'});assert '我现在不喝咖啡了' in d['data']['text']
r,d=call('forget_persists_restart','/person-memory/internal/recent',{'actor':a,'query':'台灯'});assert '银杏灯' not in d['data']['text']
(S/'http-api-results.json').write_text(json.dumps({'passed':True,'records':records,'budget':b.report()},ensure_ascii=False,indent=2));print('HTTP API PASS',len(records),b.report())
