import json,os,subprocess,sys,tarfile
from pathlib import Path
S=Path(__file__).parent
sys.path.insert(0,str(S));from budget import Budget
b=Budget(S/'budget.sqlite3')
with tarfile.open(S/'candidate-changes.tgz') as t:t.extractall(S/'work')
# Count the earlier failed local compiler attempt once in the shared ledger.
import sqlite3
with sqlite3.connect(b.path) as c: done=c.execute("SELECT count(*) FROM charges WHERE label='local_host_compiler_unavailable'").fetchone()[0]
if not done:b.reserve('case','local_host_compiler_unavailable')
for i in range(16):b.reserve('case','vision_production_host:'+str(i))
D=S/'firmware-host';D.mkdir(exist_ok=True)
with tarfile.open(S/'firmware-host.tgz') as t:t.extractall(D)
r=subprocess.run([sys.executable,str(D/'tools/run_vision_credentials_host_test.py')],capture_output=True,text=True)
(S/'vision-host.log').write_text(r.stdout+r.stderr);print(r.stdout[-2000:],r.stderr[-1000:])
print('host_exit',r.returncode,'budget',b.report())
