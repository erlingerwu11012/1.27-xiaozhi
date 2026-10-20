import json,subprocess,hashlib,tarfile,socket
from pathlib import Path
S=Path('/root/prjs/tmp/experience-repair-20261009');R=Path('/root/prjs/xiaozhi-esp32-server/main');apps=json.loads(subprocess.check_output(['pm2','jlist']))
for a in apps:
 if a['name'] in ['xiaozhi-server','manager-api']:
  e=a['pm2_env'];print(json.dumps({'name':a['name'],'id':a['pm_id'],'script':e['pm_exec_path'],'args':e.get('args'),'cwd':e['pm_cwd'],'interpreter':e.get('exec_interpreter'),'status':e['status']},ensure_ascii=False))
for port in [8040,8043,8046,18003,8020,8023,8026,8002]:
 with socket.socket() as x:print('port',port,'busy',x.connect_ex(('127.0.0.1',port))==0)
for p in (S/'manager-api/src/main/resources').glob('application*.yml'):
 print('profile',p.name)
 for line in p.read_text().splitlines():
  if any(k in line.lower() for k in ['quartz','auto-startup','job-store-type','iscluster','schedulername','threadcount']):print(line)
print('java source comparisons')
with tarfile.open('/root/prjs/releases/experience-repair-20261009/backup/sources-private.tgz') as t:
 for p in (S/'manager-api/src/main/java').rglob('*.java'):
  rel=p.relative_to(S/'manager-api');orig=R/'manager-api'/rel
  if p.read_bytes()!=orig.read_bytes():
   member=t.extractfile('manager-api/'+str(rel));same=member.read()==orig.read_bytes() if member else False
   print(str(rel),'baseline_unchanged',same)
