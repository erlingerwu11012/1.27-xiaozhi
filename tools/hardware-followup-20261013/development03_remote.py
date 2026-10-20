from pathlib import Path
import sys,subprocess,json
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
with (s/'development03.log').open('w') as log:r=subprocess.run([sys.executable,str(s/'run_dialogues.py'),'--name','development03','--mode','development','--corpus','cases-followup','--groups','combo-00,combo-03'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('exit',r.returncode);print('\n'.join((s/'development03.log').read_text().splitlines()[-14:]))
