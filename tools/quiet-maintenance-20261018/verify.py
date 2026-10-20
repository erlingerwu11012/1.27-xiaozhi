from pathlib import Path
import json,time,requests,yaml,subprocess
S=Path('/root/prjs/tmp/quiet-maintenance-20261018');ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
secret=yaml.safe_load((ROOT/'data/.config.yaml').read_text())['manager-api']['secret']
headers={'Authorization':'Bearer '+secret};base='http://127.0.0.1:18005/xiaozhi/'
account='2022326478036516866'
def api(method,path,body=None):
 r=requests.request(method,base+path,headers=headers,json=body,timeout=12);r.raise_for_status();v=r.json();assert v['code']==0;return v['data']
state=api('GET','user-identities/internal/state/'+account)
profile=next(p for p in state['voice_profiles'] if p['user_id']=='1')
actor={'account_id':account,'person_id':'1','generation':0,'directory_version':int(state['directory_version']),'mode':'personal','status':'matched','turn_id':'maintenance_verify_20261018','device_id':'ac:a7:04:fd:20:5c','agent_id':'57a71787c86f4f158c90a5c6c6e7016b','listen_epoch':0,'voiceprint_id':profile['voiceprint_id'],'template_version':int(profile['template_version']),'display_name':profile['display_name'],'captured_at':int(time.time()*1000)}
found=api('POST','person-memory/internal/search',{'actor':actor,'query':'我老婆叫什么名字'})
private=S/'deployment-private/memory-search-after.json'
private.write_text(json.dumps(found,ensure_ascii=False,indent=2));private.chmod(0o600)
print('verified_facts',json.dumps([{'text':x.get('text'),'source':x.get('source')} for x in found.get('items',[])],ensure_ascii=False))
result={'memory_search':{'status':found.get('status'),'items':len(found.get('items',[])),'sources':list(set(x.get('source','') for x in found.get('items',[])))},'processes':[]}
for app in json.loads(subprocess.check_output(['pm2','jlist'])):
 if app['pm_id'] in [21,22]:result['processes'].append({'id':app['pm_id'],'status':app['pm2_env']['status'],'restarts':app['pm2_env']['restart_time']})
(S/'post-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
