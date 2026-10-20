import bootstrap,asyncio,json,copy,traceback
from bootstrap import stage,budget,production_provider
from wire_conversation import WireConversation
ns={'__name__':'replay'};code=(stage/'run_final.py').read_text(encoding='utf-8-sig');exec(code[:code.rindex('asyncio.run(main())')],ns)
old=[json.loads(x) for x in (stage/'final-results.jsonl').read_text().splitlines()];byid={r['case']['id']:r for r in old};output=stage/'query-lifecycle-replay.jsonl';assert not output.exists()
async def group(rows):
 p,cfg=production_provider();w=await WireConversation().setup(p,cfg)
 try:
  for i,row in enumerate(rows):
   budget.reserve('case','recorded-decision-replay:'+str(row['id']));ns['prepare'](w,row,i==0);before=copy.deepcopy(w.device.state)
   q=iter([x['decision'] for x in byid[row['id']].get('decisions',[]) if x.get('kind')=='decision'])
   w.c._full_tool_harness.decide=lambda _:next(q)
   if row.get('setup')=='photo_retry':
    from plugins_func.register import Action,ActionResponse
    w.device.faults={'self_camera_take_photo':ActionResponse(Action.REQLLM,result={'ok':False,'errorCode':'vision_not_ready','message':'视觉服务尚未就绪'})} if row.get('multi_step')==0 else {}
   try:
    r=await w.turn(row['query'],noise=True);r['case']=row;await ns['read_back'](w,row,r);r['errors']=ns['check'](row,r,before)
    if row.get('setup')=='photo_retry' and row.get('multi_step')==0:r['errors']=[x for x in r['errors'] if not x.startswith('requested_operation_not_verified:')]
   except Exception:r={'case':row,'errors':['replay_exception'],'trace':traceback.format_exc()[-2000:]}
   r['evidence_type']='recorded_decision_replay_no_paid_model'
   with output.open('a') as f:f.write(json.dumps(r,ensure_ascii=False,default=str)+'\n')
   if r['errors']:print(json.dumps({'id':row['id'],'errors':r['errors'],'speech':r.get('speech'),'trace':r.get('trace')},ensure_ascii=False),flush=True)
 finally:await w.close()
async def main():
 groups={}
 for row in ns['CASES']:groups.setdefault(row.get('session') or str(row['id']),[]).append(row)
 sem=asyncio.Semaphore(4)
 async def limited(rows):
  async with sem:await group(rows)
 others=[r for r in groups.values() if not any((x.get('tool') or '').startswith('memory') for x in r)]
 memories=[r for r in groups.values() if any((x.get('tool') or '').startswith('memory') for x in r)]
 await asyncio.gather(*(limited(r) for r in others))
 for rows in memories:await group(rows)
 out=[json.loads(x) for x in output.read_text().splitlines()];fail=[{'id':x['case']['id'],'errors':x['errors'],'speech':x.get('speech')} for x in out if x['errors']]
 result={'cases':len(out),'failed':fail,'passed':not fail,'paid_requests':0,'budget':budget.report()};(stage/'query-lifecycle-replay-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False),flush=True)
asyncio.run(main())
