from pathlib import Path
import asyncio,datetime,json,os,sys,time
from types import SimpleNamespace
import requests,yaml,pymysql
S=Path('/root/prjs/tmp/quiet-maintenance-20261018');ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
os.chdir(ROOT);sys.path.insert(0,'/root/prjs/releases/quiet-maintenance-20261018/runtime')
cfg=yaml.safe_load((ROOT/'data/.config.yaml').read_text())
headers={'Authorization':'Bearer '+cfg['manager-api']['secret']}
base='http://127.0.0.1:18005/xiaozhi/'
account='2022326478036516866';device='ac:a7:04:fd:20:5c';agent='57a71787c86f4f158c90a5c6c6e7016b'
def api(method,path,payload=None):
 r=requests.request(method,base+path,headers=headers,json=payload,timeout=15);r.raise_for_status();v=r.json()
 if v.get('code')!=0:raise RuntimeError('api_rejected:'+str(v.get('code'))+':'+str(v.get('msg')))
 return v.get('data')
from core.utils.person_directory_sync import normalize_directory
from core.utils.person_identity import PersonTurn
from core.utils.habit_router import route_habit_analysis
state=normalize_directory(api('GET','user-identities/internal/state/'+account))
assert state['account_id']==account and state['mode']=='personal'
profile=next(p for p in state['voice_profiles'] if p['user_id']=='1')
actor=PersonTurn(account,'1',0,state['directory_version'],'personal','matched','maintenance_rerun_20261018',device,agent,0,profile['voiceprint_id'],profile['template_version'],profile['display_name'],int(time.time()*1000))
cfg['sys_user_id']=account;cfg['agent_id']=agent
result={'date':'2026-10-18','scope':{'account':account,'person':'1','device':device},'silent':True,'habit':{},'memory':{}}
# The real backend prepares attributed closed turns and enforces habit thresholds.
job=api('POST','person-memory/internal/behavior/prepare',actor.payload())
result['habit']['prepare_status']=job['status']
if job.get('status')=='ready':
 result['habit']['pattern_groups']=len(job['summaries'])
 if job['summaries']:
  result['habit']['status']='awaiting_live_device_worker'
 else:
  async def complete():
   conn=SimpleNamespace(config=cfg,device_id=device,loop=asyncio.get_running_loop())
   return await asyncio.to_thread(route_habit_analysis,conn,job,actor)
  result['habit']['completed']=asyncio.run(complete())
  assert result['habit']['completed']
  result['habit']['learned']=0
result['memory']=api('POST','person-memory/internal/maintenance/rerun-memory',actor.payload())
(S/'rerun-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False),flush=True)
