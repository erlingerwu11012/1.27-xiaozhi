from pathlib import Path
import subprocess,sys
s=Path('/root/prjs/tmp/hardware-followup-20261013')
with (s/'latency-baseline01.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'latency_probe.py'),'--phase','baseline','--name','baseline01','--audio','4','--exclusive'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('exit',r.returncode);print('\n'.join((s/'latency-baseline01.log').read_text().splitlines()[-5:]))
