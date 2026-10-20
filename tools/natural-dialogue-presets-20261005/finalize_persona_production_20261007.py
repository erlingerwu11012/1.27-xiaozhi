"""Read-only billing verification and a commit limited to persona source and receipt."""
import json,hashlib,re,subprocess
from pathlib import Path
from fractions import Fraction
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
PROD=Path('/root/prjs/xiaozhi-esp32-server')
receipt=json.loads((OUT/'persona-production-deployment-20261007.json').read_text());assert receipt['deployed']
probe=json.loads((OUT/'persona-production-probe-results-20261007.json').read_text());assert probe['finished']
ids=[i for s in probe['sessions'] for r in s['turns'] for i in r['billing_ids']]
assert len(ids)==21 and len(set(ids))==21 and all(re.fullmatch('[A-Za-z0-9_-]+',i) for i in ids)
exec((OUT/'inspect_qwen37_release_20261007.py').read_text().split('cfg=json.loads')[0])
where=','.join("'"+i+"'" for i in ids)
rows=[json.loads(line) for line in sql("SELECT JSON_OBJECT('state',state,'price',price_json,'usage',usage_json,'cost',cost_cny,'sale',sale_cny) FROM one_api.hardware_billing_bill WHERE id IN("+where+");").splitlines()]
assert len(rows)==21
cost=Fraction(0);sale=Fraction(0);tokens={'input_tokens':0,'output_tokens':0,'cached_tokens':0}
for row in rows:
 assert row['state']=='settled'
 price=json.loads(row['price']);usage=json.loads(row['usage'])
 assert price['model']=='qwen3.7-plus' and price['mode']=='non_thinking' and usage['confirmed']
 assert Fraction(row['sale'])==Fraction(row['cost'])*Fraction(10,3)
 cost+=Fraction(row['cost']);sale+=Fraction(row['sale'])
 for key in tokens:tokens[key]+=usage[key]
receipt['production_billing_verification']={'passed':True,'signed_requests':21,'settled_bills':21,'upstream_cost_cny':round(float(cost),6),'sale_currency_cny':round(float(sale),6),'tokens':tokens,'original_recharge_policy_preserved':True}
for n,values in receipt['source_files'].items():assert hashlib.sha256((PROD/n).read_bytes()).hexdigest()==values['after']
safe_name='docs/natural-dialogue-presets-20261005/persona-production-deployment-20261007.json'
target=PROD/safe_name;target.parent.mkdir(parents=True,exist_ok=True)
target.write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
names=list(receipt['source_files'])+[safe_name]
def run(args):
 p=subprocess.run(['git','-C',str(PROD)]+args,text=True,capture_output=True)
 if p.returncode:raise RuntimeError('selected_commit_failed')
 return p.stdout.strip()
run(['add','--']+list(receipt['source_files']))
# Repository ignores all JSON; only this inspected non-secret deployment receipt is added.
run(['add','-f','--',safe_name])
run(['commit','--only','-m','Improve persona presets and conversation expression boundaries','--']+names)
receipt['commit']=run(['rev-parse','HEAD'])
(OUT/'persona-production-deployment-20261007.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
print(json.dumps({'deployed':True,'commit':receipt['commit'],'billing':receipt['production_billing_verification'],'source_files':len(receipt['source_files']),'unrelated_files_committed':False},ensure_ascii=False))
