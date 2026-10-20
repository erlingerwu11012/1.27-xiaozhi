import pathlib,re,json,ast
p=pathlib.Path('/root/prjs/xiaozhi-esp32-server/main/manager-api/src/main/java/xiaozhi/modules/personmemory')
for f in p.rglob('*.java'):
 text=f.read_text()
 if any(k in text for k in ['class Override','max = 1024','max=1024','recent(', 'pending-']):
  print('FILE',str(f))
  lines=text.splitlines()
  hits=[i for i,s in enumerate(lines) if re.search(r'1024|recent\(|pending-|role|business|tool|select.*Recent|queryRecent|setText|"text"',s,re.I)]
  selected=set(j for i in hits for j in range(max(0,i-2),min(len(lines),i+4)))
  for i in sorted(selected)[:140]:print(str(i+1)+': '+lines[i])
root=pathlib.Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
import hashlib
for n in ['core/utils/tool_harness/contracts.py','core/utils/tool_harness/runtime.py','core/utils/recent_memory.py']:
 print('HASH',n,hashlib.sha256((root/n).read_bytes()).hexdigest())
