"""Execution replay only: recorded decisions, current frozen code, zero network calls."""
import asyncio,copy,dataclasses,hashlib,json,sys,uuid
from pathlib import Path
stage=Path(__file__).parent;base=stage/'frozen-20261008-budget-final';current=stage/'frozen-20261008-budget-delta'
sys.path.insert(0,str(current))
import run_budget_tests
from bootstrap import production_provider
from baseline_support import make_baseline,run_baseline
from test_support import check,argument_matches,effective_arguments
from core.utils.tool_harness.contracts import contract
old=[json.loads(x) for x in (base/'budget-results.jsonl').read_text().splitlines() if x.strip()]
selected=set(json.loads((current/'budget-plan.json').read_text())['replaces_single_tools'])
rows=[r for r in old if r['chain']=='candidate' and not (r['suite']=='single' and r['expected_tool'] in selected)]
pack=json.loads((current/'pack.json').read_text());orig={(s,r['id']):r for s,rs in [('single',pack['cases']),('complex',pack['complex']),('holdout',json.loads((base/'holdout.json').read_text()))] for r in rs}
async def main():
 template,cfg=production_provider();sem=asyncio.Semaphore(6);out=[]
 def forbidden(*a,**kw):raise RuntimeError('offline_replay_network_forbidden')
 # This also protects against an accidental native model request.
 template.client._client.event_hooks['request'].insert(0,forbidden)
 async def one(r):
  async with sem:
   provider=copy.copy(template);provider.response_with_functions=forbidden
   c,m,spy=make_baseline(provider,cfg,asyncio.get_running_loop(),harness=True);turns=[];needs_live=False
   source=orig[r['suite'],r['id']]
   try:
    for index,t in enumerate(r['turns']):
     expected=source.get('turns',[source])[index]
     choices=list(t['events'])
     def recorded(_):
      while choices:
       item=choices.pop(0)
       if item['kind']!='decision':continue
       if item.get('decision') is not None:return item['decision']
       raise ValueError('recorded_schema_validation')
      raise RuntimeError('recorded_decisions_exhausted_needs_live')
     provider.decision=recorded
     c.listen_epoch+=1;c.person_turn=dataclasses.replace(c.person_turn,listen_epoch=c.listen_epoch,turn_id=uuid.uuid4().hex)
     offset=len(m.calls)
     result=await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(c.executor,run_baseline,c,m,spy,t['user']),95)
     calls=m.calls[offset:];needs_live=needs_live or 'recorded_decisions_exhausted' in result.error
     if r['suite']=='single':passed=check(source,result,calls)
     else:
      wanted=expected.get('expected',[])
      passed=not expected.get('mode') or result.mode==expected['mode']
      passed=passed and sum(contract(x.tool).write for x in result.results)==sum(contract(x['tool']).write for x in wanted)
      for target in wanted:
       matches=[x for x in result.results if x.tool==target['tool']]
       passed=passed and len(matches)==1 and matches[0].state=='completed' and all(argument_matches(k,effective_arguments(target['tool'],matches[0].arguments).get(k),v) for k,v in target['arguments'].items())
      if expected.get('no_calls'):passed=passed and not calls
     turns.append({'user':t['user'],'passed':bool(passed),'outcome':result.model_dump(),'calls':calls,'expected':expected.get('expected')})
    record={'id':r['id'],'repeat':r['repeat'],'suite':r['suite'],'passed':all(x['passed'] for x in turns),'needs_live':needs_live,'turns':turns,'evidence':'recorded-decision-execution-replay','network_requests':0,'original_row':source}
    out.append(record)
   finally:
    c.executor.shutdown(wait=False,cancel_futures=True);c._full_tool_harness.ledger.close()
 await asyncio.gather(*(one(r) for r in rows))
 template.client.close()
 target=current/'offline-replay.jsonl'
 if target.exists():raise RuntimeError('Preserve existing replay evidence')
 target.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in out))
 summary={'records':len(out),'passed':sum(r['passed'] for r in out),'needs_live':[{'id':r['id'],'suite':r['suite']} for r in out if r['needs_live']],'failed':[{'id':r['id'],'suite':r['suite']} for r in out if not r['passed'] and not r['needs_live']],'network_requests':0,'postprocessor_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
 (current/'offline-replay-summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary))
asyncio.run(main())
