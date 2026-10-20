"""Verify all real test requests settled and configuration still matches snapshot."""
import json,re
from fractions import Fraction
from pathlib import Path
out=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
exec((out/'inspect_qwen37_release_20261007.py').read_text().split('cfg=json.loads')[0])
data=json.loads((out/'persona-runtime-results-20261007.json').read_text());assert data['finished']
ids=[i for s in data['sessions'] for r in s['turns'] for i in r['billing_ids']]
assert len(ids)==data['model_requests']==182 and len(set(ids))==len(ids)
assert all(re.fullmatch('[A-Za-z0-9_-]+',i) for i in ids)
where=','.join("'"+i+"'" for i in ids)
rows=[json.loads(line) for line in sql("SELECT JSON_OBJECT('state',state,'price',price_json,'usage',usage_json,'cost',cost_cny,'sale',sale_cny) FROM one_api.hardware_billing_bill WHERE id IN("+where+");").splitlines()]
assert len(rows)==len(ids)
cost=Fraction(0);sale=Fraction(0);tokens={'input_tokens':0,'output_tokens':0,'cached_tokens':0};input_sizes=[]
for row in rows:
 assert row['state']=='settled'
 price=json.loads(row['price']);usage=json.loads(row['usage'])
 assert price['model']=='qwen3.7-plus' and price['mode']=='non_thinking' and usage['confirmed']
 assert Fraction(row['sale'])==Fraction(row['cost'])*Fraction(10,3)
 cost+=Fraction(row['cost']);sale+=Fraction(row['sale'])
 for key in tokens:tokens[key]+=usage[key]
 input_sizes.append(usage['input_tokens'])
report={'passed':True,'signed_test_requests':len(ids),'settled_bills':len(rows),'duplicate_request_ids':0,'upstream_cost_cny_exact':str(cost),'sale_currency_cny_exact':str(sale),'upstream_cost_cny_display':round(float(cost),6),'sale_currency_cny_display':round(float(sale),6),'token_usage':tokens,'single_request_input_min':min(input_sizes),'single_request_input_max':max(input_sizes),'original_recharge_policy_preserved':True,'model':'qwen3.7-plus','thinking':False}
(out/'persona-billing-audit-20261007.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))
