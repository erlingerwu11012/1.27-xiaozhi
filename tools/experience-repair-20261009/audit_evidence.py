from pathlib import Path
import re,tarfile,json,hashlib
S=Path('tools/experience-repair-20261009'); E=S/'evidence'; hits=[];checked=0
patterns=[('dashscope_literal',r'\bsk-[A-Za-z0-9]{20,}\b'),('aws_key',r'\bAKIA[A-Z0-9]{16}\b'),('private_key',r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----')]
def check(name,data):
 global checked
 checked+=1
 try:text=data.decode('utf-8')
 except UnicodeDecodeError:return
 for label,pat in patterns:
  if re.search(pat,text):hits.append({'file':name,'pattern':label})
for p in E.rglob('*'):
 if p.is_file():
  check(p.relative_to(E).as_posix(),p.read_bytes())
  if p.name.endswith('.tgz'):
   with tarfile.open(p) as t:
    for m in t.getmembers():
     if m.isfile():check(p.name+'/'+m.name,t.extractfile(m).read())
result={'scanned_files_and_archive_members':checked,'credential_literal_findings':hits,'private_backup_exported':False,'notes':'Pattern scan supplements an explicit export whitelist; it is not a proof that every possible secret format is detectable.'};(E/'artifact-privacy-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result));assert not hits
