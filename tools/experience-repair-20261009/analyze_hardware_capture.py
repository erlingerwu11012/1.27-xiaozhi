import json,re,datetime,collections
from pathlib import Path
S=Path('tools/experience-repair-20261009');a=json.loads((S/'active-hardware-capture.json').read_text(encoding='utf-8-sig'));R=Path(a['output']);manifest=json.loads((R/'manifest.json').read_text());start=datetime.datetime.fromtimestamp(manifest['started_ns']/1e9,datetime.timezone(datetime.timedelta(hours=8))).strftime('%H:%M:%S');lines=(R/'server-0.log').read_text(encoding='utf-8',errors='replace').splitlines();turns=[];cur=None;warn=[];receipts=[]
for i,l in enumerate(lines,1):
 m=re.match(r'261009 (\d\d:\d\d:\d\d)',l)
 if not m or m[1]<start:continue
 t=m[1]
 if '大模型收到用户消息:' in l:
  content=l.split('大模型收到用户消息:',1)[1].strip()
  try:content=json.loads(content).get('content',content)
  except:pass
  cur={'time':t,'line':i,'user':content,'speech':[],'tools':[]};turns.append(cur)
 if '发送音频消息: SentenceType.FIRST,' in l and cur:cur['speech'].append(l.split('SentenceType.FIRST,',1)[1].strip())
 if 'harness.receipt ' in l:
  receipt=json.loads(l.split('harness.receipt ',1)[1]);receipts.append({'time':t,'line':i,**receipt})
  if cur:cur['tools'].append({k:receipt[k] for k in ['tool','state','error']})
 if '-ERROR-' in l or '-WARNING-' in l:warn.append({'time':t,'line':i,'text':l})
(R/'test-transcript.json').write_text(json.dumps(turns,ensure_ascii=False,indent=2),encoding='utf-8');(R/'test-receipts.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2),encoding='utf-8');(R/'test-warnings.json').write_text(json.dumps(warn,ensure_ascii=False,indent=2),encoding='utf-8')
print('START',start,'TURNS',len(turns),'RECEIPTS',len(receipts),dict(collections.Counter(r['state'] for r in receipts)))
for x in turns:print(json.dumps(x,ensure_ascii=False))
print('OTHER WARNINGS')
for x in warn:
 if '声纹识别相似度' not in x['text']:print(json.dumps(x,ensure_ascii=False))
print('CAPTURE EVENTS',dict(collections.Counter(json.loads(x)['event'] for x in (R/'events.jsonl').read_text(encoding='utf-8').splitlines())))
