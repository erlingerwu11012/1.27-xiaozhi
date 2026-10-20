from pathlib import Path
import json
S=Path(__file__).parent
for suffix in ['results.jsonl','freeze.json','console.log','summary.json']:
 p=S/('resume-final-'+suffix)
 if p.exists():p.rename(S/('resume-state-validation-failures-'+suffix))
(S/'state-validation-review.json').write_text(json.dumps({'failures':['reg-100 explicit relative level omitted by model; normalize before schema validation','reg-163 latest omitted object update must supersede initial shipping state and strip runtime wrapper','holdout-43 negative action statement misdetected as completion'],'original_outputs_retained':True},indent=2))
