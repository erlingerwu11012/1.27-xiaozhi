from pathlib import Path
import sys,subprocess,tarfile,json
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
from budget import Budget
for script,name in [('test_ingress_followup.py','ingress-01'),('vision_http_followup.py','vision-http-01')]:
 with (s/(name+'.log')).open('x') as log:r=subprocess.run([sys.executable,str(s/script)],cwd=s,stdout=log,stderr=subprocess.STDOUT)
 print(name,r.returncode);print('\n'.join((s/(name+'.log')).read_text().splitlines()[-10:]));assert r.returncode==0
print('budget',Budget().report())
