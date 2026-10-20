import json,re
from fractions import Fraction
from pathlib import Path
out=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
exec((out/'inspect_qwen37_release_20261007.py').read_text().split('cfg=json.loads')[0])
receipt=json.loads((out/'qwen37-official-deployment-20261007.json').read_text())
usage=receipt['usage'];request=usage['upstream_request_id'];assert re.fullmatch('[a-zA-Z0-9_-]+',request)
rows=sql("SELECT JSON_OBJECT('id',id,'state',state,'cost_cny',cost_cny,'sale_cny',sale_cny,'allocations',allocations) FROM one_api.hardware_billing_bill WHERE JSON_UNQUOTE(JSON_EXTRACT(usage_json,'$.upstream_request_id'))='"+request+"';").splitlines()
assert len(rows)==1
bill=json.loads(rows[0]);cost=Fraction(bill['cost_cny']);sale=Fraction(bill['sale_cny'])
expected=Fraction(2*(usage['input_tokens']-usage['cached_tokens'])+8*usage['output_tokens'],1000000)+Fraction(4*usage['cached_tokens'],10000000)
assert bill['state']=='settled' and cost==expected and sale==cost*Fraction(10,3)
allocations=json.loads(bill['allocations']);assert allocations
report={'passed':True,'single_settled_bill':True,'input_tokens':usage['input_tokens'],'output_tokens':usage['output_tokens'],'cached_tokens':usage['cached_tokens'],'upstream_cost_cny_exact':str(cost),'sale_cny_exact':str(sale),'sale_multiplier':'10/3','original_recharge_conversion_preserved':True,'allocations_count':len(allocations)}
(out/'qwen37-production-billing-audit-20261007.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
