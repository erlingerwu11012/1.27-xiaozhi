import bootstrap,asyncio,json
from bootstrap import stage
ns={'__name__':'focus'};code=(stage/'run_final.py').read_text(encoding='utf-8-sig');exec(code[:code.rindex('asyncio.run(main())')],ns);ns['REPORT']=stage/'fixed-failures-real.jsonl'
async def main():
 for row in ns['CASES']:
  if row['id'] in [89,99,128,134]:await ns['run_group']([row])
asyncio.run(main())
