from pathlib import Path
import subprocess,sys
s=Path('/root/prjs/tmp/hardware-followup-20261013')
with (s/'network-stream-02.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'stream_network_test.py')],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('network',r.returncode,flush=True);assert r.returncode==0
with (s/'final01.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'run_dialogues.py'),'--name','final01','--mode','final','--corpus','cases-followup'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('final',r.returncode);print('\n'.join((s/'final01.log').read_text().splitlines()[-15:]))
