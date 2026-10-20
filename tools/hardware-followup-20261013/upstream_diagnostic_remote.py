import subprocess,json,re,time,httpx
print('containers',subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines())
for origin in ['https://dashscope.aliyuncs.com','https://dashscope-intl.aliyuncs.com']:
 t=time.monotonic()
 try:r=httpx.get(origin,timeout=5);print('upstream_reachability',origin,r.status_code,round(time.monotonic()-t,2))
 except Exception as e:print('upstream_reachability',origin,type(e).__name__)
for container in subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines():
 if any(x in container.lower() for x in ['one-api','oneapi','new-api']):
  result=subprocess.run(['docker','logs','--since','30m','--tail','300',container],capture_output=True,text=True)
  data=result.stdout+result.stderr
  for pattern in ['context deadline exceeded','timeout','timed out','no available channel','insufficient','401','429','500','503','POST /v1/chat/completions']:
   count=len(re.findall(re.escape(pattern),data,re.I))
   if count:print('gateway_log_category',container,pattern,count)
  from pathlib import Path
  p=Path('/root/prjs/tmp/hardware-followup-20261013/private-gateway-diagnostic.log');p.write_text(data);p.chmod(0o600)
