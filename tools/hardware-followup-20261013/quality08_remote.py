from pathlib import Path
import sys,subprocess,tarfile
s=Path('/root/prjs/tmp/hardware-followup-20261013')
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
steps=[([str(s/'test_quality_followup.py'),'Quality.test_greeting_does_not_invent_shared_past'],'greeting-unit03.log'),([str(s/'quality_probe.py'),'--name','quality07','--extended-greeting'],'quality07.log')]
for args,name in steps:
 with (s/name).open('x') as log:r=subprocess.run([sys.executable]+args,cwd=s,stdout=log,stderr=subprocess.STDOUT)
 print(name,r.returncode,flush=True);print((s/name).read_text(),flush=True)
 if r.returncode:break
