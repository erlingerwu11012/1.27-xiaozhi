"""Real billed model, isolated executor. Never connects a production device."""
import argparse,asyncio,hashlib,json,time
from pathlib import Path
from bootstrap import production_provider,system_prompt,stage
from test_support import PACK,connection,check

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=0);parser.add_argument('--concurrency',type=int,default=4);parser.add_argument('--output',default='model-smoke.jsonl');parser.add_argument('--repeats',type=int,default=1);args=parser.parse_args()
    provider,cfg=production_provider()
    persona=system_prompt(cfg)
    rows=PACK['cases'] if not args.limit else [r for r in PACK['cases'] if r['group']!='negative'][::8][:args.limit]
    semaphore=asyncio.Semaphore(args.concurrency);count=0;failed=0
    out=stage/args.output
    def decide(messages,events):
        before=time.monotonic()
        try:
            value=provider.decision(messages)
            events.append({'decision':value,'usage':provider.last_usage,'elapsed_ms':round((time.monotonic()-before)*1000,2)})
            return value
        except Exception as e:
            events.append({'error':type(e).__name__,'elapsed_ms':round((time.monotonic()-before)*1000,2)})
            raise
    async def test(row,repeat):
        nonlocal count,failed
        async with semaphore:
            events=[];conn,m,h=connection(decide=lambda msgs:decide(msgs,events));start=time.monotonic()
            outcome=await h.run(row['user'],[{'role':'system','content':persona},{'role':'user','content':row['user']}])
            okay=check(row,outcome,m.calls)
            record={'id':row['id'],'repeat':repeat,'model':provider.model_name,'temperature':provider.temperature,'thinking':False,'billing_gateway':True,'pack_hash':PACK['sha256'],'user':row['user'],'group':row['group'],'expected_tool':row['tool'],'expected_arguments':row.get('arguments'),'passed':okay,'elapsed_ms':round((time.monotonic()-start)*1000,2),'events':events,'calls':m.calls,'outcome':outcome.model_dump()}
            with out.open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
            count+=1;failed+=not okay
            if count%10==0:print(json.dumps({'done':count,'failed':failed}),flush=True)
            h.ledger.close()
    out.write_text('')
    await asyncio.gather(*(test(row,r) for row in rows for r in range(args.repeats)))
    print(json.dumps({'total':count,'failed':failed,'passed':count-failed,'output':str(out)}),flush=True)
if __name__=='__main__':asyncio.run(main())
