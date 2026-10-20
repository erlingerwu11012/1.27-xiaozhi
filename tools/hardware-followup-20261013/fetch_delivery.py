from pathlib import Path
import subprocess,tarfile,hashlib,json
S=Path(__file__).resolve().parent;D=S/'delivery';E=D/'evidence';E.mkdir(parents=True,exist_ok=True)
remote='/root/prjs/tmp/hardware-followup-20261013/'
for name in ['delivery-evidence.tgz','delivery-live-status.json','historical-data-diff-summary.json','backup-restore-evidence.json']:
 subprocess.run(['scp','-q','root@121.40.239.140:'+remote+name,str(D/name)],check=True,timeout=90)
with tarfile.open(D/'delivery-evidence.tgz') as archive:
 assert all(m.isfile() and (E/m.name).resolve().is_relative_to(E.resolve()) for m in archive.getmembers())
 for member in archive.getmembers():
  target=E/member.name;target.parent.mkdir(parents=True,exist_ok=True)
  with archive.extractfile(member) as source,target.open('wb') as dest:
   while chunk:=source.read(1024*1024):dest.write(chunk)
manifest=json.loads((E/'delivery-evidence-manifest.json').read_text())
for name,meta in manifest.items():assert hashlib.sha256((E/name).read_bytes()).hexdigest()==meta['sha256'],name
print('downloaded_and_verified_evidence_files',len(manifest))
