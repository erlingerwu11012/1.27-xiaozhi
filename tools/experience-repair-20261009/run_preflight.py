import bootstrap,asyncio,json,copy,time
from bootstrap import stage,budget
from wire_conversation import WireConversation
from test_support import PACK,decision,step
from pathlib import Path
# Load validation helpers without starting the paid final suite.
ns={'__name__':'preflight_helpers'};code=(stage/'run_final.py').read_text(encoding='utf-8-sig');exec(code[:code.rindex('asyncio.run(main())')],ns)
class Fake:
 last_usage={}
 def __init__(self,n,args):self.n=n;self.args=args
 def decision(self,messages):
  if self.n in {'memory_correct','memory_forget'}:
   ctx=json.loads(messages[-1]['content'].split('[本轮可信目录与执行状态]\n')[-1]);rows=ctx.get('verified_results',[])
   if not rows:return decision(step('memory_search',{'query':'咖啡'}),finished=False,authorized_writes=[self.n])
   self.args['match']=rows[-1]['payload']['items'][0]['text']
  return decision(step(self.n,self.args))
async def main():
 cfg=json.load(open('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json'));records=[]
 for n in ['memory_search','memory_correct','memory_forget','reminder_action','habit_learn','habit_confirm','self_screen_set_render_options','camera_face_enroll_start','add_reminder']:
  f=PACK['fixtures'][n];p=Fake(n,copy.deepcopy(f['arguments']));w=await WireConversation().setup(p,cfg);row={'id':n,'tool':n,'arguments':f['arguments'],'query':f['query'],'group':'tool','setup':n}
  try:
   budget.reserve('case','preflight:'+n);ns['prepare'](w,row,True);before=copy.deepcopy(w.device.state);r=await w.turn(f['query']);await ns['read_back'](w,row,r);r['errors']=ns['check'](row,r,before);records.append(r);print(n,r['speech'],r['errors'],flush=True)
  finally:await w.close()
 (stage/'preflight-state-results.json').write_text(json.dumps(records,ensure_ascii=False,default=str,indent=2));print(budget.report())
asyncio.run(main())
