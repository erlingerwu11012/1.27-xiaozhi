"""Export synthetic test evidence; keep production backups and credentials private."""
from pathlib import Path
import collections,hashlib,json,re,sqlite3,time,zipfile
S=Path(__file__).parent;D=S/'delivery29';D.mkdir(exist_ok=True)
credential=re.compile(r'^(?:authorization|password|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|ws[_-]?token|vision[_-]?token|token|credential|credentials)$',re.I)
def clean(value):
 if isinstance(value,dict):return {k:('[REDACTED]' if credential.match(k) else clean(v)) for k,v in value.items()}
 if isinstance(value,list):return [clean(v) for v in value]
 if isinstance(value,str):
  value=re.sub(r'Bearer\s+[A-Za-z0-9._~+/=-]+','Bearer [REDACTED]',value)
  value=re.sub(r'([?&](?:token|key|secret|api_key)=)[^&\s"\']+',r'\1[REDACTED]',value,flags=re.I)
 return value
rows=[json.loads(x) for x in (S/'final27-results.jsonl').read_text().splitlines()]
usage=[]
for row in rows:
 for index,decision in enumerate(row.get('decisions',[])):
  if decision.get('usage'):usage.append({'group':row['group'],'turn':row['turn'],'decision_index':index,**decision['usage']})
total=lambda key:sum(u.get(key) or 0 for u in usage)
tokens={'scope':'Only the accepted 360-case mixed-version corpus, not every historical attempt','requests_with_recorded_usage':len(usage),'input_tokens':total('prompt_tokens'),'output_tokens':total('completion_tokens'),'cache_hit_tokens':sum((u.get('prompt_tokens_details') or {}).get('cached_tokens') or 0 for u in usage),'cache_creation_tokens':sum((u.get('prompt_tokens_details') or {}).get('cache_creation_input_tokens') or 0 for u in usage),'full_run_cost_cny':None,'cost_note':'Gateway request IDs were not consistently captured; shared-account charges cannot be attributed exactly to this test run.'}
cache=[]
for p in sorted(S.glob('*.jsonl')):
 if 'private' in p.name:continue
 for line in p.read_text().splitlines():
  try:record=json.loads(line)
  except ValueError:continue
  for index,d in enumerate(record.get('decisions',[])):
   detail=(d.get('usage') or {}).get('prompt_tokens_details') or {}
   create=detail.get('cache_creation_input_tokens');hit=detail.get('cached_tokens')
   if create or hit:
    entry={'source':p.name,'group':record.get('group'),'turn':record.get('turn'),'decision_index':index,'cache_creation_tokens':create,'cache_hit_tokens':hit}
    if create or not cache:cache.append(entry)
    elif len([x for x in cache if x.get('cache_hit_tokens')])<5 and hit:cache.append(entry)
cache=cache[:40]
assert any(c.get('cache_creation_tokens') for c in cache) and any(c.get('cache_hit_tokens') for c in cache)
(D/'token-and-cache-evidence.json').write_text(json.dumps({'tokens':tokens,'cache_examples':cache,'missing_fields':'unknown, not zero; per-layer hits are not asserted'},ensure_ascii=False,indent=2))
with sqlite3.connect(S/'budget.sqlite3') as db:
 db.row_factory=sqlite3.Row;charges=[dict(r) for r in db.execute('SELECT * FROM charges ORDER BY id')]
for row in charges:
 if row.get('metadata'):
  try:row['metadata']=json.loads(row['metadata'])
  except ValueError:pass
(D/'all-attempt-budget-ledger.json').write_text(json.dumps(clean(charges),ensure_ascii=False,indent=2))
patterns=['final*-results.jsonl','final*-summary.json','final*-frozen.json','final*-freeze.json','*-latency.jsonl','tools-final16-tools.jsonl','retrieval02-results.jsonl','protocol04-summary.json','protocol04-device-evidence.json','full-ingress-evidence.json','api-v2-memory-evidence.json','acceptance-review27.json','release29-candidate-evidence.json','release27-stage.json','memory-api-package26.json','isolated-config-fixture27.json','isolated-config-cache-fix27.json','budget-approval-*.json','incremental-authorization.json','holdout-exposure.json','deployment29.json']
patterns += ['release29-hash-check.json']
export={}
for pattern in patterns:
 for p in S.glob(pattern):
  if p.name in export:continue
  if p.suffix=='.jsonl':data='\n'.join(json.dumps(clean(json.loads(line)),ensure_ascii=False) for line in p.read_text().splitlines())+'\n'
  else:data=json.dumps(clean(json.loads(p.read_text())),ensure_ascii=False,indent=2)
  export[p.name]=data
with zipfile.ZipFile(D/'automated-evidence29.zip','w',zipfile.ZIP_DEFLATED) as out:
 for name,data in sorted(export.items()):out.writestr(name,data)
 for name in ['token-and-cache-evidence.json','all-attempt-budget-ledger.json']:out.write(D/name,name)
inventory=json.loads((S/'release-preflight-v2.json').read_text())
names=set(inventory['changed_source'])|{'core/handle/helloHandle.py','core/providers/tools/device_mcp/mcp_handler.py'}
with zipfile.ZipFile(D/'patch-source29.zip','w',zipfile.ZIP_DEFLATED) as out:
 for name in sorted(names):
  p=S/'work'/name
  if not name.startswith('test/') and p.is_file():out.write(p,'server/'+name)
 out.write(S/'work/agent-base-prompt-v2.txt','server/agent-base-prompt-v2.txt')
 for p in sorted((S/'java').glob('*.java')):out.write(p,'manager-api/'+p.name)
 out.write(Path('/root/prjs/releases/harness-stream-20261012/serve.py'),'release/serve.py')
hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in D.iterdir() if p.is_file() and p.name!='SHA256.json'}
(D/'SHA256.json').write_text(json.dumps(hashes,indent=2));print(json.dumps({'files':list(hashes),'accepted_corpus_usage_requests':len(usage),'cache_creation_evidence':True,'cache_hit_evidence':True}))
