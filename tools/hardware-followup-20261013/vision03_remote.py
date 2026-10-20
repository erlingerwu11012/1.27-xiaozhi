from pathlib import Path
import sys,subprocess,tarfile,json
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
from budget import Budget
b=Budget();c=b.reserve('case','vision-http-02-fixture-setup-failed');b.finish(c,{'passed':False,'error':'PIL unavailable; embedded synthetic JPEG instead; no paid/model request','reservation_note':'setup failure recorded after execution; original log retained'})
with (s/'vision-http-03.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'vision_http_followup.py')],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print(r.returncode);print('\n'.join((s/'vision-http-03.log').read_text().splitlines()[-15:]));print('budget',b.report())
