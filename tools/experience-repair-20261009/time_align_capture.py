import json,re,bisect,datetime,collections
from pathlib import Path
S=Path('tools/experience-repair-20261009');R=Path(json.loads((S/'active-hardware-capture.json').read_text(encoding='utf-8-sig'))['output']);raw=(R/'firmware-0001.raw').read_bytes();index=[json.loads(x) for x in (R/'firmware-index.jsonl').read_text().splitlines()];ends=[x['end'] for x in index];parts=raw.splitlines(keepends=True);offset=0;lines=[];dated=[]
for i,data in enumerate(parts,1):
 pos=bisect.bisect_left(ends,offset+len(data));pos=min(pos,len(index)-1);ts=datetime.datetime.fromtimestamp(index[pos]['local_ns']/1e9,datetime.timezone(datetime.timedelta(hours=8))).strftime('%H:%M:%S.%f')[:-3];l=data.decode('utf-8',errors='replace').rstrip();lines.append(l);dated.append(f'{ts} {l}');offset+=len(data)
(R/'firmware-timed.log').write_text('\n'.join(dated),encoding='utf-8')
for lo,hi in [(3113,3155),(4829,4844),(1660,1710),(1875,1915),(4364,4385),(5190,5219)]:
 print('WINDOW',lo,hi)
 for i in range(lo,hi+1):
  if any(x in lines[i-1] for x in ['TaskDiag:','TASKCFG','TASKLIST','TASKOPT','TASKCPU']):continue
  print(i,dated[i-1])
L=(R/'server-0.log').read_text(encoding='utf-8').splitlines();vp=[]
for i,l in enumerate(L,1):
 if re.match(r'261009 17:(3[2-9]|4[0-4]):',l) and ('声纹识别相似度' in l or '声纹识别成功' in l):vp.append(l)
print('VOICEPRINT WARNINGS',len([x for x in vp if '低于' in x]));print('VOICEPRINT SUCCESS',len([x for x in vp if '成功' in x]));print('NULL BYTE COUNT',raw.count(b'\0'))
print('ALARM FIRE EVIDENCE')
for i,l in enumerate(lines,1):
 if re.search(r'(?:alarm|闹钟).*(?:trigger|ring|due|响)|(?:trigger|ring).*(?:alarm|闹钟)',l,re.I):print(i,dated[i-1])
