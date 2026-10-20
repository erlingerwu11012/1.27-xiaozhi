
from pathlib import Path
import hashlib,json,os,shutil,time,subprocess
root=Path('/root/prjs/tmp').resolve();source=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/models/SenseVoiceSmall/model.pt').resolve()
expected='833ca2dcfdf8ec91bd4f31cfac36d6124e0c459074d5e909aec9cabe6204a3ea';before=shutil.disk_usage('/').free;rows=[]
for name in ['experience-repair-20261009/work/models/SenseVoiceSmall/model.pt','nvs-habit-renewal-20261007/work/xiaozhi-server/models/SenseVoiceSmall/model.pt']:
 p=root/name
 if p.is_symlink():rows.append({'path':str(p),'status':'already_linked'});continue
 assert p.resolve().is_relative_to(root) and p.is_file() and p.resolve()!=source
 with p.open('rb') as f:
  digest=hashlib.sha256()
  for block in iter(lambda:f.read(1048576),b''):digest.update(block)
  h=digest.hexdigest()
 assert h==expected, 'model differs; retain it'
 size=p.stat().st_size;temp=p.with_name(p.name+'.dedupe-link');temp.symlink_to(source);os.replace(temp,p)
 rows.append({'path':str(p),'sha256':h,'logical_bytes_removed':size,'status':'verified_duplicate_replaced_with_symlink'})
subprocess.run(['apt-get','clean'],check=True,capture_output=True)
after=shutil.disk_usage('/').free;report={'at':time.time(),'free_before':before,'free_after':after,'bytes_reclaimed':after-before,'actions':rows,'production_model_retained':str(source),'backups_retained':True}
stage=root/'hardware-repair-20261009';(stage/'disk-cleanup.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
