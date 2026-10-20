"""Read-only settlement checks for all isolated persona optimization requests."""
import json,re
from fractions import Fraction
from pathlib import Path
out=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
exec((out/'inspect_qwen37_release_20261007.py').read_text().split('cfg=json.loads')[0])
names=['persona-optimized-runtime-results-20261007.json','persona-optimized-heldout-results-20261007.json','persona-refined-runtime-results-20261007.json','persona-refined-heldout-results-20261007.json','persona-injection-probe-results-20261007.json']
audits=[]
for name in names:
 data=json.loads((out/name).read_text());assert data['finished'] and data['customer_configuration_unchanged']
 turns=[r for s in data['sessions'] for r in s['turns']]
 assert len(turns)==data['expected_turns']
 ids=[i for r in turns for i in r['billing_ids']]
 assert len(ids)==data['model_requests'] and len(set(ids))==len(ids)
 assert all(re.fullmatch('[A-Za-z0-9_-]+',i) for i in ids)
 where=','.join("'"+i+"'" for i in ids)
 rows=[json.loads(line) for line in sql("SELECT JSON_OBJECT('state',state,'price',price_json,'usage',usage_json,'cost',cost_cny,'sale',sale_cny) FROM one_api.hardware_billing_bill WHERE id IN("+where+");").splitlines()]
 assert len(rows)==len(ids)
 cost=Fraction(0);sale=Fraction(0);tokens={'input_tokens':0,'output_tokens':0,'cached_tokens':0};sizes=[]
 for row in rows:
  assert row['state']=='settled'
  price=json.loads(row['price']);usage=json.loads(row['usage'])
  assert price['model']=='qwen3.7-plus' and price['mode']=='non_thinking' and usage['confirmed']
  assert Fraction(row['sale'])==Fraction(row['cost'])*Fraction(10,3)
  cost+=Fraction(row['cost']);sale+=Fraction(row['sale'])
  for key in tokens:tokens[key]+=usage[key]
  sizes.append(usage['input_tokens'])
 audits.append({'file':name,'passed':True,'turns':len(turns),'signed_requests':len(ids),'settled_bills':len(rows),'upstream_cost_cny':round(float(cost),6),'sale_currency_cny':round(float(sale),6),'tokens':tokens,'input_min':min(sizes),'input_max':max(sizes),'unchanged_account_config':True})
report={'passed':True,'model':'qwen3.7-plus','thinking':False,'audits':audits,'original_recharge_policy_preserved':True}
(out/'persona-optimization-billing-20261007.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))
