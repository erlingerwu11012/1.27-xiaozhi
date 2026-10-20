from pathlib import Path
import subprocess,sys,tarfile
s=Path('/root/prjs/tmp/hardware-followup-20261013')
with tarfile.open(s/'source-delta.tgz') as archive:
 member=archive.getmember('test_ota_followup.py');archive.extract(member,s,filter='data')
with (s/'ota-api-01.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'test_ota_followup.py')],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('exit',r.returncode);print((s/'ota-api-01.log').read_text()[-6000:])
