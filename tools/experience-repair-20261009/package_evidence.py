import json,sqlite3,hashlib,tarfile,time
from pathlib import Path
S=Path(__file__).parent
with sqlite3.connect(S/'budget.sqlite3') as d:
 charges=[{'kind':k,'label':l,'metadata':json.loads(m) if m else None} for k,l,m in d.execute('SELECT kind,label,metadata FROM charges')]
models=[x['metadata'] or {} for x in charges if x['kind']=='model'];usage={k:sum((m.get('usage') or {}).get(k,0) or 0 for m in models) for k in ['prompt_tokens','completion_tokens','total_tokens']}
from budget import Budget
summary={'at':time.time(),'budget':Budget(S/'budget.sqlite3').report(),'model_usage':usage,'http_status_counts':{str(status):sum(m.get('status')==status for m in models) for status in set(m.get('status') for m in models)},'actual_model_names':sorted({m.get('model') for m in models if m.get('model')}),'currency_cost':None,'currency_cost_reason':'test request IDs were not retained with billing transaction IDs; cannot separate concurrent account usage reliably','production_deployed':False,'hardware_tested':False,'final_source_manifest':{n:hashlib.sha256((S/'work'/n).read_bytes()).hexdigest() for n in json.loads((S/'changed-files.json').read_text(encoding='utf-8-sig'))}}
(S/'review-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
names=['review-summary.json','final-results.jsonl','final-freeze.json','final-cases.json','aborted-first-final-results.jsonl','aborted-first-final-freeze.json','aborted-first-note.json','aborted-second-final-results.jsonl','aborted-second-final-freeze.json','aborted-second-note.json','postfix-focused-results.jsonl','fact-fix-focus-results.jsonl','fixed-failures-real.jsonl','development-model.jsonl','http-api-results.json','vision-http-results.json','real-tts-results.json','ws-boundary-results.json','relative-canonical-results.json','context-preservation-results.json','low-cost-summary.json','focused-regression-summary.json','latest-regression-summary.json','lifecycle-summary.json','repair-tests-summary.json','changed-files.json','candidate-changes.tgz','memory_quarantine.py']
names += [p.name for p in S.glob('audio-*.wav')]
with tarfile.open(S/'review-evidence.tgz','w:gz') as t:
 for n in names:
  if (S/n).is_file():t.add(S/n,arcname=n)
print(json.dumps({'budget':summary['budget'],'tokens':usage,'evidence_files':len(names),'production_deployed':False},ensure_ascii=False))
