from pathlib import Path
import subprocess,os,json,signal,time,sys,tarfile,shutil
s=Path('/root/prjs/tmp/hardware-followup-20261013');env=dict(os.environ,FOLLOWUP_BUILD_VERSION='03');sys.path.insert(0,str(s))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
from budget import Budget
b=Budget();charge=json.loads((s/'firmware-build-charge.json').read_text())['id'];b.finish(charge,{'status':'compiled','log':'local firmware-build-01.log','flashed':False})
subprocess.run([sys.executable,str(s/'build_api.py')],cwd=s,env=env,check=True)
info=json.loads((s/'isolated-manager-pid.json').read_text());pid=info['pid'];cmd=Path('/proc/'+str(pid)+'/cmdline').read_bytes().decode().replace('\0',' ')
assert str(s) in cmd and info['jar'] in cmd and '--server.port=18006' in cmd
os.kill(pid,signal.SIGTERM)
for _ in range(60):
 if not Path('/proc/'+str(pid)).exists():break
 time.sleep(.2)
subprocess.run([sys.executable,str(s/'start_isolated_api.py')],cwd=s,env=env,check=True)
subprocess.run([sys.executable,str(s/'test_followup.py')],cwd=s,check=True)
charge=b.reserve('case','freeze-formal-baseline-runtime')
if not (s/'baseline-work').exists():shutil.copytree('/root/prjs/releases/harness-stream-20261012/runtime',s/'baseline-work',ignore=shutil.ignore_patterns('data','tmp','__pycache__','.git','logs','*.log','*.sqlite3'))
b.finish(charge,{'baseline':'harness-stream-20261012','production_modified':False})
with (s/'development01.log').open('w') as log:
 result=subprocess.run([sys.executable,str(s/'run_dialogues.py'),'--name','development01','--mode','development','--corpus','cases-followup','--groups','combo-00,combo-01,combo-02,combo-03'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('development_exit',result.returncode)
print('\n'.join((s/'development01.log').read_text().splitlines()[-12:]))
