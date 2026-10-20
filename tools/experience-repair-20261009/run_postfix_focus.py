import bootstrap,asyncio,json
from bootstrap import stage
ns={'__name__':'focused_review'};code=(stage/'run_final.py').read_text(encoding='utf-8-sig');exec(code[:code.rindex('asyncio.run(main())')],ns);ns['REPORT']=stage/'postfix-focused-results.jsonl'
async def main():
 cases=ns['CASES'];groups={}
 for r in cases:
  if r['id'] in {153,156,158} or r.get('session') in {'chat1','chat3','multi3','multi4'}:groups.setdefault(r.get('session') or str(r['id']),[]).append(r)
 for rows in groups.values():await ns['run_group'](rows)
asyncio.run(main())
