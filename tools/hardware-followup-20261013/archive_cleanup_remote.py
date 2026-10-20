from pathlib import Path
import json,hashlib,os,time
s=Path('/root/prjs/tmp/hardware-followup-20261013');active=json.loads((s/'isolated-manager-pid.json').read_text())
assert active['jar']==str(s/'candidate-api-05.jar') and Path('/proc/'+str(active['pid'])).exists()
rows=[]
for version in ['03','04']:
 p=(s/('candidate-api-'+version+'.jar')).resolve();assert p.parent==s and p!=Path(active['jar'])
 digest=hashlib.sha256(p.read_bytes()).hexdigest();assert digest==json.loads((s/('api-package-evidence-'+version+'.json')).read_text())['candidate_sha256']
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit():continue
  try:cmd=(proc/'cmdline').read_bytes()
  except (FileNotFoundError,ProcessLookupError,PermissionError):continue
  assert str(p).encode() not in cmd,'still referenced by process'
 rows.append({'file':str(p),'sha256':digest,'bytes':p.stat().st_size,'local_verified_copy':'E:/github/github_code/all/4.30/tools/hardware-followup-20261013/private-rebuildable-archives/'+p.name})
 p.unlink()
f=os.statvfs('/');e={'removed_only_stopped_test_jars':rows,'available_bytes':f.f_bavail*f.f_frsize,'time':time.time(),'formal_rollback_unchanged':True}
(s/'rebuildable-cleanup-04.json').write_text(json.dumps(e,indent=2));print('recovered',sum(x['bytes'] for x in rows),'available',e['available_bytes'])
