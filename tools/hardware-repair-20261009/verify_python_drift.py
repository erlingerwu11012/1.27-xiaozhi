from pathlib import Path
import json
S=Path(__file__).parent;A=Path('/root/prjs/releases/experience-repair-20261009/runtime');B=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server');changed=set(json.loads((S/'changed-files.json').read_text(encoding='utf-8-sig')));bad=[];count=0
for p in A.rglob('*.py'):
 n=p.relative_to(A)
 if n.parts[0] in {'test','data','models','logs','tmp'} or str(n) in changed:continue
 count+=1
 if not (B/n).exists() or p.read_bytes()!=(B/n).read_bytes():bad.append(str(n))
r={'passed':not bad,'unchanged_python_files':count,'unexpected_differences':bad};(S/'python-drift-preflight.json').write_text(json.dumps(r,indent=2));print(json.dumps(r));assert r['passed']
