from pathlib import Path
import os,subprocess
s=Path('/root/prjs/tmp/hardware-followup-20261013');v=os.statvfs('/root/prjs');print('available',v.f_bavail*v.f_frsize)
for p in (s/'baseline-work/models').rglob('*'):
 if p.is_file() and p.stat().st_size>8*1024*1024:print('remaining_copy',p.relative_to(s),p.stat().st_size)
print('runtime_jar', (s/'manager-api/xiaozhi-esp32-api.jar').exists())
print('copied_api_jars', [(str(p.relative_to(s)),p.stat().st_size) for p in s.glob('candidate*.jar')])
