from pathlib import Path
import subprocess,os
s=Path('/root/prjs/tmp/hardware-followup-20261013')
for p in sorted(s.iterdir()):
 if p.is_dir():
  result=subprocess.run(['du','-sb',str(p)],capture_output=True,text=True)
  if result.returncode==0:
   size=int(result.stdout.split()[0])
   if size>20*1024*1024:print('directory_bytes',p.name,size)
for p in [s/'baseline-work',s/'manager-api']:
 for child in p.iterdir():
  result=subprocess.run(['du','-sb',str(child)],capture_output=True,text=True)
  if result.returncode==0 and int(result.stdout.split()[0])>40*1024*1024:print('large_child',str(child.relative_to(s)),result.stdout.split()[0])
v=os.statvfs('/root/prjs');print('available',v.f_bavail*v.f_frsize,'free_including_reserved',v.f_bfree*v.f_frsize)
