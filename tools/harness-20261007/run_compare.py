"""Identical frozen inputs through actual ConnectionHandler; all effects simulated."""
import argparse,asyncio,hashlib,json,time,dataclasses,uuid
from bootstrap import production_provider,stage
from baseline_support import make_baseline,run_baseline
from test_support import PACK,check,argument_matches
import core.connection
core.connection.print=lambda *a,**k:None
# The same trusted context clock is supplied to both native and harness paths.
from core.utils import current_time
current_time.get_prompt_time_context=lambda:{'current_datetime':'2026-10-07 19:30:00','today_date':'2026-10-07','today_weekday':'星期三','lunar_date':'八月廿七','timezone':'Asia/Shanghai'}

async def main():
    p=argparse.ArgumentParser();p.add_argument('--repeats',type=int,default=3);p.add_argument('--concurrency',type=int,default=6)
    p.add_argument('--limit',type=int,default=0);p.add_argument('--chain',choices=['baseline','candidate','both'],default='both');p.add_argument('--output',default='comparison.jsonl');p.add_argument('--suite',choices=['single','complex','holdout'],default='single')
    a=p.parse_args();provider,cfg=production_provider();sem=asyncio.Semaphore(a.concurrency)
    rows=PACK['cases'] if a.suite=='single' else PACK['complex'] if a.suite=='complex' else json.loads((stage/'holdout.json').read_text())
    if a.limit:rows=[r for r in rows if r.get('group')!='negative'][::8][:a.limit]
    chains=['baseline','candidate'] if a.chain=='both' else [a.chain]
    output=stage/a.output
    if output.exists():raise RuntimeError('Evidence output exists; use a fresh filename')
    count=failed=0
    manifest=json.loads((stage/'candidate-manifest.json').read_text())
    code_hash=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    async def test(row,repeat,chain):
        nonlocal count,failed
        async with sem:
            start=time.monotonic();c,m,spy=make_baseline(provider,cfg,asyncio.get_running_loop(),harness=chain=='candidate')
            fixture_ready=time.monotonic();request_elapsed=0.0
            try:
                turns=row.get('turns',[row]);evidence=[]
                for turn in turns:
                    c.listen_epoch+=1;c.person_turn=dataclasses.replace(c.person_turn,listen_epoch=c.listen_epoch,turn_id=uuid.uuid4().hex)
                    previous_calls=len(m.calls);previous_events=len(spy.events)
                    turn_started=time.monotonic()
                    outcome=await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(c.executor,run_baseline,c,m,spy,turn['user']),95)
                    turn_elapsed=time.monotonic()-turn_started;request_elapsed+=turn_elapsed
                    calls=m.calls[previous_calls:];events=spy.events[previous_events:]
                    if a.suite=='single':passed=check(turn,outcome,calls)
                    else:
                        from core.utils.tool_harness.contracts import contract
                        expected=turn.get('expected',[])
                        passed=not turn.get('mode') or outcome.mode==turn['mode']
                        writes=[r for r in outcome.results if contract(r.tool).write]
                        passed=passed and len(writes)==sum(contract(e['tool']).write for e in expected)
                        for wanted in expected:
                            matching=[r for r in outcome.results if r.tool==wanted['tool']]
                            passed=passed and len(matching)==1 and matching[0].state=='completed' and all(argument_matches(k,matching[0].arguments.get(k),v) for k,v in wanted['arguments'].items())
                        passed=passed and not (not expected and any(contract(x['tool']).write for x in calls))
                        if turn.get('no_calls'):passed=passed and not calls
                    passed=passed and not any(e.get('error_type') and e.get('error_kind')!='validation' for e in events)
                    evidence.append({'user':turn['user'],'passed':passed,'elapsed_ms':round(turn_elapsed*1000,2),'outcome':outcome.model_dump(),'calls':calls,'events':events,'expected':turn.get('expected')})
                record={'outcome':evidence[-1]['outcome'],'passed':all(t['passed'] for t in evidence),'turns':evidence,'schema_tools_shown':sorted(c._full_tool_harness.shown) if hasattr(c,'_full_tool_harness') else sorted(m.tools)}
            except Exception as exc:
                request_elapsed=max(request_elapsed,time.monotonic()-fixture_ready)
                record={'passed':False,'runner_error':type(exc).__name__}
            finally:
                c.executor.shutdown(wait=False,cancel_futures=True)
                if hasattr(c,'_full_tool_harness'):c._full_tool_harness.ledger.close()
            record.update({'id':row['id'],'repeat':repeat,'chain':chain,'user':row.get('user'),'group':row.get('group',a.suite),'expected_tool':row.get('tool'),'expected_arguments':row.get('arguments'),'events':spy.events,'calls':m.calls,'elapsed_ms':round(request_elapsed*1000,2),'fixture_setup_ms':round((fixture_ready-start)*1000,2),'test_wall_ms':round((time.monotonic()-start)*1000,2),'pack_hash':PACK['sha256'],'code_hash':code_hash,'model':provider.model_name,'temperature':provider.temperature,'thinking':False,'billing_gateway':True,'evidence':'simulation','chat_executor':'ConnectionHandler.executor (same separation as production)' })
            with output.open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
            count+=1;failed+=not record['passed']
            if count%10==0:print(json.dumps({'done':count,'failed':failed}),flush=True)
    await asyncio.gather(*(test(row,r,chain) for row in rows for r in range(a.repeats) for chain in chains))
    print(json.dumps({'done':count,'failed':failed,'output':str(output)}),flush=True)
if __name__=='__main__':asyncio.run(main())
