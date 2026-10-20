import bootstrap,asyncio,json
from bootstrap import stage
ns={'__name__':'facts_focus'};code=(stage/'run_final.py').read_text(encoding='utf-8-sig');exec(code[:code.rindex('asyncio.run(main())')],ns);ns['REPORT']=stage/'fact-fix-focus-results.jsonl'
asyncio.run(ns['run_group']([r for r in ns['CASES'] if r.get('session')=='chat3']))
