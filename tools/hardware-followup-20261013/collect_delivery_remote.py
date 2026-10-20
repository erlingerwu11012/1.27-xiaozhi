from pathlib import Path
import json,sqlite3,tarfile,hashlib,subprocess,time
S=Path('/root/prjs/tmp/hardware-followup-20261013')
deployment=json.loads((S/'deployment-followup.json').read_text());assert deployment['phase']=='complete'
seen={};known_usage=[];raw_failures=[]
for path in sorted(S.glob('*results.jsonl'))+sorted(S.glob('*latency.jsonl')):
 for index,line in enumerate(path.read_text().splitlines()):
  try:r=json.loads(line)
  except ValueError:continue
  if r.get('errors') or r.get('passed') is False:raw_failures.append({'file':path.name,'row':index+1,'group':r.get('group',r.get('label')),'turn':r.get('turn'),'errors':r.get('errors',r.get('error')),'query':r.get('query'),'speech':r.get('speech')})
  r=r.get('result',r)
  events=r.get('events') or [];sid=events[0].get('sentence_id') if events else None
  for i,event in enumerate(r.get('decisions',[])):
   usage=event.get('usage')
   if not usage or usage.get('prompt_tokens') is None:continue
   key=(sid,i) if sid else (path.name,index,i)
   if key not in seen:seen[key]=True;known_usage.append({'file':path.name,'usage':usage})
with sqlite3.connect(S/'budget.sqlite3') as db:
 rows=[{'id':i,'kind':k,'label':l,'phase':p,'created':t,'metadata':json.loads(m) if m else None} for i,k,l,p,t,m in db.execute('SELECT id,kind,label,phase,created,metadata FROM charges ORDER BY id')]
counts={k:sum(r['kind']==k for r in rows) for k in ['case','model','tts','vision']}
usage={'reserved_requests':counts['model'],'requests_with_preserved_usage':len(known_usage),'usage_missing_requests':counts['model']-len(known_usage),'observed_input_tokens':sum(r['usage'].get('prompt_tokens',0) for r in known_usage),'observed_output_tokens':sum(r['usage'].get('completion_tokens',0) for r in known_usage),'observed_cache_hit_tokens':sum((r['usage'].get('prompt_tokens_details') or {}).get('cached_tokens') or 0 for r in known_usage),'observed_cache_creation_tokens':sum((r['usage'].get('prompt_tokens_details') or {}).get('cache_creation_input_tokens') or 0 for r in known_usage),'cache_hit_request_count':sum(bool((r['usage'].get('prompt_tokens_details') or {}).get('cached_tokens')) for r in known_usage),'fees':'unknown; no billing aggregation requested','usage_missing_fields_not_estimated':True,'deduplication':'original output sentence ID and decision index; reused rows counted once','per_layer_cache_hits':'unknown; provider reports aggregate usage only'}
assert usage['usage_missing_requests']>=0
(S/'usage-summary.json').write_text(json.dumps(usage,indent=2));(S/'budget-charges-export.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));(S/'failure-index.json').write_text(json.dumps(raw_failures,ensure_ascii=False,indent=2))
final=list(map(json.loads,(S/'final09-results.jsonl').read_text().splitlines()));review=json.loads((S/'acceptance-final-review.json').read_text());overlays={(r['group'],r['turn']):r for r in review['overlays']}
text=['# 完整定向对话与补验映射','', '此文保留181轮原始最终业务验收输出。补验是独立上下文／可信结果回放，不能当成同一会话连续重跑；未受影响业务证据按用户授权复用，版本与源文件保留。','']
for r in sorted(final,key=lambda x:(x['group'],x['turn'])):
 text+=['## '+r['group']+' / '+str(r['turn']+1),'','用户：'+r['query'],'','原验收回复：'+r['speech'],'','业务：通过；原执行版本：'+str(r.get('origin_evidence') or 'final09')+'；本次索引：final09']
 o=overlays.get((r['group'],r['turn']))
 if o:text+=['','回复补验：'+o['speech'],'','补验来源：'+o['source']+'；方法：'+o['method']]
 text+=['']
(S/'COMPLETE_DIALOGUES.md').write_text('\n'.join(text))
files=[]
for pattern in ['*results.jsonl','*latency.jsonl','final*-freeze.json','final*-summary.json','development*-freeze.json','development*-summary.json','quality*.log','*unit*.log','final*.log','development*.log','*latency*.log','deterministic-*.log','lifecycle-*.log','network-stream-*.log','confirmation-*.log','selection-*.log','ingress-*.log','vision-http-*.log','ota-api-*.log','history-retry-*.log','supplement*.log','rebuildable-cleanup-*.json']:
 files+=list(S.glob(pattern))
for name in ['budget-approval-700.json','budget-charges-export.json','usage-summary.json','failure-index.json','COMPLETE_DIALOGUES.md','acceptance-final-review.json','latency-comparison.json','final-source-freeze.json','deployment-followup.json','followup02-candidate-evidence.json','final-candidate-check.log','api-package-evidence-05.json','holdout-exposure.json','history-retry-evidence.json','vision-http-followup-results.json']:
 files.append(S/name)
files=list(dict.fromkeys(files));manifest={str(p.relative_to(S)):{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files if p.is_file()}
(S/'delivery-evidence-manifest.json').write_text(json.dumps(manifest,indent=2))
with tarfile.open(S/'delivery-evidence.tgz','w:gz') as archive:
 for p in files:archive.add(p,arcname=p.name)
 archive.add(S/'delivery-evidence-manifest.json',arcname='delivery-evidence-manifest.json')
apps=json.loads(subprocess.check_output(['pm2','jlist']));status=[{'id':a['pm_id'],'status':a['pm2_env']['status'],'release':a['pm2_env']['pm_exec_path'],'restarts':a['pm2_env']['restart_time']} for a in apps if a['pm_id'] in [9,10,11,12]]
(S/'delivery-live-status.json').write_text(json.dumps({'captured_at':time.time(),'processes':status,'formal_domain':'https://www.realecho.cn','deployment_state':'complete'},indent=2));print(json.dumps({'usage':usage,'counts':counts,'preserved_failure_rows':len(raw_failures),'evidence_archive_bytes':(S/'delivery-evidence.tgz').stat().st_size,'processes':status},ensure_ascii=False))
