from pathlib import Path
import subprocess,sys,tarfile,json
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
from budget import Budget
b=Budget()
with (s/'lifecycle-04.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'test_lifecycle_followup.py')],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('lifecycle',r.returncode,flush=True);print('\n'.join((s/'lifecycle-04.log').read_text().splitlines()[-12:]),flush=True)
assert r.returncode==0
# Reuse only complete setting/card conversations; changed public recipient and
# complaint wording cases run again. Keep original version provenance.
rows=[json.loads(x) for x in (s/'final04-results.jsonl').read_text().splitlines()]
reuse=[dict(x,origin_evidence=x.get('origin_evidence') or 'final04') for x in rows if x['group'] in {'combo-04','combo-05'}]
assert len(reuse)==10 and not any(x['errors'] for x in reuse)
(s/'accepted-incremental-results.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in reuse))
with (s/'final06.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'run_dialogues.py'),'--name','final06','--mode','final','--corpus','cases-followup','--reuse-from','accepted-incremental'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('final',r.returncode);print('\n'.join((s/'final06.log').read_text().splitlines()[-12:]));print('budget',b.report())
