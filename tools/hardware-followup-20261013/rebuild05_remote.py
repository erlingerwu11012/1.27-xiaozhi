from pathlib import Path
import subprocess,os,json,signal,time,sys
s=Path('/root/prjs/tmp/hardware-followup-20261013');env=dict(os.environ,FOLLOWUP_BUILD_VERSION='05');sys.path.insert(0,str(s))
subprocess.run([sys.executable,str(s/'build_api.py')],cwd=s,env=env,check=True)
info=json.loads((s/'isolated-manager-pid.json').read_text());pid=info['pid'];cmd=Path('/proc/'+str(pid)+'/cmdline').read_bytes().decode().replace('\0',' ')
assert str(s) in cmd and info['jar'] in cmd and '--server.port=18006' in cmd
os.kill(pid,signal.SIGTERM)
for _ in range(60):
 if not Path('/proc/'+str(pid)).exists():break
 time.sleep(.2)
subprocess.run([sys.executable,str(s/'start_isolated_api.py')],cwd=s,env=env,check=True)
for script,name in [('test_followup.py','deterministic-05'),('test_ota_followup.py','ota-api-03'),('test_lifecycle_followup.py','lifecycle-01')]:
 with (s/(name+'.log')).open('x') as log:r=subprocess.run([sys.executable,str(s/script)],cwd=s,stdout=log,stderr=subprocess.STDOUT)
 print(name,r.returncode,flush=True);print((s/(name+'.log')).read_text()[-3000:],flush=True);assert r.returncode==0
