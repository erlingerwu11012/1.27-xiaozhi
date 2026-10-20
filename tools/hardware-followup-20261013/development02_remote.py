from pathlib import Path
import sys,json,tarfile,subprocess
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
from budget import Budget
b=Budget();data=json.loads((s/'host-charges-01.json').read_text())
for name,charges in data.items():
 for charge in charges:b.finish(charge,{'passed':name!='tts-owner-and-playback','suite':name,'failure':'test_fixture_parameter_shadowing' if name=='tts-owner-and-playback' else None,'hardware':False})
(s/'host-charges-02.json').write_text(json.dumps([b.reserve('case','firmware-host-02:tts:'+str(i)) for i in range(24)]))
with (s/'development02.log').open('w') as log:
 result=subprocess.run([sys.executable,str(s/'run_dialogues.py'),'--name','development02','--mode','development','--corpus','cases-followup','--groups','combo-00,combo-01,combo-02,combo-03'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('development_exit',result.returncode)
print('\n'.join((s/'development02.log').read_text().splitlines()[-14:]))
print('budget',b.report())
