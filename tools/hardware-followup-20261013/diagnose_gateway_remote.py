from pathlib import Path
import sys,json,subprocess,urllib.parse,time
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
import bootstrap
p,c=bootstrap.production_provider()
print('provider',{'model':p.model_name if hasattr(p,'model_name') else None,'base':str(p.client.base_url),'timeout':str(p.client.timeout)})
print('pm2',[(x['name'],x['pm_id'],x['pm2_env']['status']) for x in json.loads(subprocess.check_output(['pm2','jlist']))])
import httpx
for url in ['http://127.0.0.1:18005/xiaozhi/actuator/health','http://127.0.0.1:18006/xiaozhi/actuator/health',str(p.client.base_url)]:
 start=time.monotonic()
 try:r=httpx.get(url,timeout=5);print('health',url, r.status_code,round(time.monotonic()-start,2))
 except Exception as e:print('health',url,type(e).__name__,round(time.monotonic()-start,2))
p.client.close()
