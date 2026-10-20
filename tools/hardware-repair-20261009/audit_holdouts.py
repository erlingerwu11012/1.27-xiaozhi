from pathlib import Path
import json,collections
S=Path(__file__).parent
fail=collections.defaultdict(set)
for p in S.glob('resume*-results.jsonl'):
 if p.name=='resume-final-results.jsonl':continue
 for line in p.read_text().splitlines():
  try:r=json.loads(line)
  except ValueError:continue
  cid=r['case']['id']
  if cid.startswith('holdout-') and r.get('errors'):fail[cid].add(p.name)
rows=[json.loads(x) for x in (S/'resume-final-results.jsonl').read_text().splitlines()]
flag={x['case']['id'] for x in rows if x['case'].get('independent_holdout')}
print(json.dumps({'prior_holdout_errors':{k:sorted(v) for k,v in fail.items()},'flagged_independent_with_prior_errors':sorted(flag & set(fail))},ensure_ascii=False))
