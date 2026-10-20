import re,json,collections
from pathlib import Path
p=Path('/root/.pm2/logs/xiaozhi-server-out.log'); c=collections.Counter()
for x in p.read_text(errors='replace').splitlines()[-120:]:
 if '-ERROR-' in x or '-WARNING-' in x:
  m=re.search(r'\[([^\]]+)\]-(ERROR|WARNING)-([^:：\n]{0,75})',x)
  if m:c[(m[1],m[2],re.sub(r'[0-9a-f]{8,}','[id]',m[3]))]+=1
print(json.dumps([{'module':a,'level':b,'message_prefix':c,'count':n} for (a,b,c),n in c.items()],ensure_ascii=False))
