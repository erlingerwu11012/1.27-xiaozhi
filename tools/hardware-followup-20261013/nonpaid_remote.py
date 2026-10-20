from pathlib import Path
import sys,json,hashlib,os,tarfile,subprocess
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
from budget import Budget
b=Budget()
for charge in json.loads((s/'host-charges-02.json').read_text()):b.finish(charge,{'passed':True,'suite':'actual TTS ingress, playback, owner checks ASan UBSan','hardware':False})
removed=[]
formal=Path('/root/prjs/releases/harness-stream-20261012/runtime')
for original in (formal/'models').rglob('*'):
 if original.is_file() and original.stat().st_size>=8*1024*1024 and not (s/'baseline-work'/original.relative_to(formal)).exists():removed.append({'path':str(s/'baseline-work'/original.relative_to(formal)),'restore_source':str(original),'bytes':original.stat().st_size,'sha256':hashlib.sha256(original.read_bytes()).hexdigest()})
(s/'rebuildable-cleanup-03.json').write_text(json.dumps({'removed_verified_duplicate_models':removed,'copied_manager_jar_kept':'hash differs from formal; cleanup aborted before deleting it'},indent=2))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
with (s/'network-stream-01.log').open('w') as log:result=subprocess.run([sys.executable,str(s/'stream_network_test.py')],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('network_exit',result.returncode);print('\n'.join((s/'network-stream-01.log').read_text().splitlines()[-16:]));print('budget',b.report())
