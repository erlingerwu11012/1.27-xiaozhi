from pathlib import Path
import json,hashlib,ast,shutil
S=Path('/root/prjs/tmp/hardware-followup-20261013');R=Path('/root/prjs/releases/harness-followup-20261013')
v=json.loads((S/'vision-http-followup-results.json').read_text());print('vision',type(v).__name__,len(v),[r['status'] for r in v])
changes=[]
for p in (S/'work').rglob('*'):
 rel=p.relative_to(S/'work')
 if not p.is_file() or p.is_symlink() or any(x in {'__pycache__','logs','tmp','data','.git','test','models','build','target'} for x in rel.parts) or p.suffix not in {'.py','.txt','.yaml','.yml','.json'} or str(rel)=='config.yaml':continue
 if p.suffix=='.py':ast.parse(p.read_text(),filename=str(rel))
 target=R/'runtime'/rel
 if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=hashlib.sha256(p.read_bytes()).hexdigest():changes.append(str(rel))
print('stage_delta',changes,'candidate_entry_allows02',"'followup02'" in (S/'candidate_entry_remote.py').read_text(),'free',shutil.disk_usage('/').free)
