from pathlib import Path
import hashlib,json
S=Path(__file__).parent;A=Path('/root/prjs/xiaozhi-esp32-server/main/manager-api');B=S/'manager-api';changed={'src/main/java/xiaozhi/modules/personmemory/'+n for n in ['RecentArchiveService.java','PersonMemoryService.java','PersonMemoryController.java']}|{str(next((B/'src/main/java').rglob('ConfigServiceImpl.java')).relative_to(B))};bad=[];count=0
for p in (A/'src/main/java').rglob('*.java'):
 n=str(p.relative_to(A))
 if n in changed:continue
 count+=1
 if not (B/n).exists() or p.read_bytes()!=(B/n).read_bytes():bad.append(n)
r={'passed':not bad,'unchanged_java_files':count,'unexpected_differences':bad};(S/'java-drift-preflight.json').write_text(json.dumps(r,indent=2));print(json.dumps(r));assert r['passed']
