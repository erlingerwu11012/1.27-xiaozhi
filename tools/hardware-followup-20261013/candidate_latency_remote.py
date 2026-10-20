from pathlib import Path
import sys,subprocess
s=Path('/root/prjs/tmp/hardware-followup-20261013')
with (s/'candidate01-latency.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'latency_probe.py'),'--phase','candidate','--name','candidate01','--audio','6','--final','--exclusive'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print(r.returncode);print((s/'candidate01-latency.log').read_text())
