from pathlib import Path
import subprocess,sys,json,tarfile
S=Path(__file__).parent;sys.path.insert(0,str(S));from budget import Budget
b=Budget(S/'budget.sqlite3')
with tarfile.open(S/'firmware-host.tgz') as t:t.extractall(S)
for i in range(11):b.reserve('case','alarm-clock-host:'+str(i))
H=S/'alarm-host';subprocess.run(['gcc','-c','cJSON.c','-o','cJSON.o'],cwd=H,check=True)
subprocess.run(['g++','-std=c++17','-pthread','-I.','alarm_manager.cc','test_alarm.cpp','cJSON.o','-o','test_alarm'],cwd=H,check=True)
r=subprocess.run([str(H/'test_alarm')],capture_output=True,text=True,timeout=10);(S/'alarm-host.log').write_text(r.stdout+r.stderr);print(r.stdout,r.stderr);assert r.returncode==0
for i in range(16):b.reserve('case','vision-credentials-host:'+str(i))
r=subprocess.run([sys.executable,str(S/'vision-host/tools/run_vision_credentials_host_test.py')],capture_output=True,text=True,timeout=60);(S/'vision-host.log').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stdout+r.stderr
(S/'firmware-host-results.json').write_text(json.dumps({'alarm_clock_cases':11,'vision_cases':16,'passed':True,'hardware':False,'budget':b.report()},indent=2));print(b.report())
