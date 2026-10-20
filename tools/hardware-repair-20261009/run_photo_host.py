from pathlib import Path
import subprocess,json,sys
S=Path(__file__).parent;sys.path.insert(0,str(S));from budget import Budget
b=Budget(S/'budget.sqlite3')
for i in range(6):b.reserve('case','actual-photo-worker-host:'+str(i))
subprocess.run(['g++','-std=c++17','-pthread',str(S/'photo-worker-host.cpp'),'-o',str(S/'photo-worker-host')],check=True)
r=subprocess.run([str(S/'photo-worker-host')],capture_output=True,text=True,timeout=10)
(S/'photo-worker-host-results.json').write_text(json.dumps({'passed':r.returncode==0,'cases':6,'output':r.stdout,'errors':r.stderr,'hardware':False,'source':'extracted actual PhotoTaskEntry with host camera/network stubs'},indent=2));print(r.stdout,r.stderr);assert r.returncode==0
