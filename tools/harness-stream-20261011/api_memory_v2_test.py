"""Real isolated management HTTP: immediate resave, IDs, versions and tombstones."""
import bootstrap,asyncio,dataclasses,uuid,json
from bootstrap import stage,budget,production_provider
from wire_conversation import WireConversation
from core.utils.person_identity import activate,deactivate
from core.utils.recent_memory import add,search,override

async def main():
 p,cfg=production_provider();w=await WireConversation().setup(p,cfg);evidence=[]
 async def call(label,fn,check):
  q=budget.reserve('case','api-v2:'+label)
  try:
   result=await fn();assert check(result),(label,result);evidence.append({'case':label,'result':result,'passed':True});budget.finish(q,{'passed':True});return result
  except Exception as exc:evidence.append({'case':label,'passed':False,'error':str(exc)});budget.finish(q,{'passed':False});raise
 try:
  for i in range(5):
   w.c.person_turn=dataclasses.replace(w.c.person_turn,turn_id=uuid.uuid4().hex);t=activate(w.c,w.c.person_turn)
   try:
    await call('forget-all-'+str(i),lambda:override(w.c,'forget','*'),lambda r:r.get('local_applied'))
    a=await call('immediate-add-'+str(i),lambda:add(w.c,'喜欢咖啡'),lambda r:r.get('local_applied'))
    r=await call('immediate-read-'+str(i),lambda:search(w.c,'喜欢咖啡'),lambda r:any(x['text']=='喜欢咖啡' for x in r.get('items',[])))
    row=next(x for x in r['items'] if x['text']=='喜欢咖啡')
    await call('versioned-correct-'+str(i),lambda:override(w.c,'correct','喜欢咖啡','喜欢绿茶',record_id=row['record_id'],expected_version=row['version']),lambda r:r.get('local_applied'))
    await call('correct-readback-'+str(i),lambda:search(w.c,'喜欢咖啡'),lambda r:any(x['text']=='喜欢绿茶' for x in r.get('items',[])) and all(x['text']!='喜欢咖啡' for x in r.get('items',[])))
    charge=budget.reserve('case','api-v2:stale-version-'+str(i))
    try:
     try:bad=await override(w.c,'correct','喜欢咖啡','喜欢红茶',record_id=row['record_id'],expected_version=row['version'])
     except Exception:bad={'rejected':True}
     assert bad.get('rejected') or bad.get('status')=='error',bad
     evidence.append({'case':'stale-version-'+str(i),'passed':True,'result':bad});budget.finish(charge,{'passed':True})
    except Exception:budget.finish(charge,{'passed':False});raise
    rr=await search(w.c,'喜欢绿茶');current=next(x for x in rr['items'] if x['text']=='喜欢绿茶')
    await call('versioned-forget-'+str(i),lambda:override(w.c,'forget','喜欢绿茶',record_id=current['record_id'],expected_version=current['version']),lambda r:r.get('local_applied'))
    await call('forget-readback-'+str(i),lambda:search(w.c,'喜欢绿茶'),lambda r:not any('喜欢绿茶' in x['text'] for x in r.get('items',[])))
   finally:deactivate(t)
 finally:
  (stage/'api-v2-memory-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));await w.close();p.client.close()
 print('API_MEMORY_V2',len(evidence),'passed',flush=True)
asyncio.run(main())
