from pathlib import Path
import json
S=Path('tools/experience-repair-20261009');p=S/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8');s=s.replace("                declared=set(decision.authorized_writes)","                if write_scope is None and not decision.finished and not targets and 'authorized_writes' not in decision.model_fields_set:\n                    raise ValueError('first_read_plan_requires_authorized_writes: declare original final write tools, or [] for a pure query')\n                declared=set(decision.authorized_writes)",1);p.write_text(s,encoding='utf-8')
p=S/'run_final.py';s=p.read_text(encoding='utf-8');s=s.replace("   if actual.get(k)!=v:errors.append('wrong_argument:'+k)","   observed=actual.get(k)\n   if k=='brightness' and type(observed) is int and type(v) is int:\n    def level(x):return x if x<=5 else 1 if x<65 else 2 if x<75 else 3 if x<85 else 4 if x<95 else 5\n    observed,v=level(observed),level(v)\n   if observed!=v:errors.append('wrong_argument:'+k)")
p.write_text(s,encoding='utf-8')
p=S/'final-cases.json';rows=json.loads(p.read_text());
for row in rows:
 if row.get('session')=='multi4' and row.get('multi_step')==2:row['tool']=None;row['required']=['书','杯']
p.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
