import asyncio,json
from bootstrap import production_provider
from baseline_support import make_baseline,run_baseline
from test_support import PACK,check
async def main():
    p,cfg=production_provider()
    for name in ['self_audio_speaker_set_volume','alarm_set','add_reminder','habit_list']:
        row=next(r for r in PACK['cases'] if r['tool']==name)
        c,m,spy=make_baseline(p,cfg,asyncio.get_running_loop())
        out=await asyncio.to_thread(run_baseline,c,m,spy,row['user'])
        print(json.dumps({'user':row['user'],'passed':check(row,out,m.calls),'outcome':out.model_dump(),'calls':m.calls,'events':spy.events},ensure_ascii=False),flush=True)
        c.executor.shutdown(wait=False,cancel_futures=True)
asyncio.run(main())
