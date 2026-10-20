import argparse
cli=argparse.ArgumentParser();cli.add_argument('--name',default='retrieval02');opt=cli.parse_args()
import bootstrap,asyncio,json,types
from bootstrap import stage,budget,production_provider
from wire_conversation import WireConversation
from core.utils.tool_harness.runtime import Harness
from core.utils.tool_harness.ledger import Ledger
from core.providers.tools.base import ToolDefinition,ToolType
from core.utils.reminder_interaction import close_interaction

class MissOnce(Harness):
 def prompt(self,*args,**kwargs):
  messages=super().prompt(*args,**kwargs)
  if not getattr(self,'injected_miss',False):
   self.injected_miss=True
   dynamic=messages[-1]['content'];prefix,body=dynamic.split('\n',1);context=json.loads(body)
   context['schemas']=[];context['fault_injection']='server initial recall returned no match; supplemental retrieval remains available'
   messages[-1]['content']=prefix+'\n'+json.dumps(context,ensure_ascii=False);self.shown=set()
  return messages

async def main():
 out=stage/(opt.name+'-results.jsonl');assert not out.exists()
 for label,query,target in [('initial_miss','请实际查询纽约现在的当地时间，不要只按北京时间推算。','get_world_time'),('unaudited','请实际查询一下电池剩余电量。',None)]:
  charge=budget.reserve('case','retrieval:'+label);provider,cfg=production_provider();w=await WireConversation().setup(provider,cfg);close_interaction(w.c)
  try:
   if target:w.c._full_tool_harness=MissOnce(w.c,ledger=Ledger(':memory:'))
   else:
    d={'type':'function','function':{'name':'self_battery_secret','description':'查询电池剩余电量','parameters':{'type':'object','properties':{}}}}
    w.device.tools['self_battery_secret']=ToolDefinition('self_battery_secret',d,ToolType.DEVICE_MCP)
   r=await w.turn(query);r['label']=label
   modes=[e.get('decision',{}).get('mode') for e in r['decisions']]
   if target:
    assert modes.count('retrieve')==1,(modes,r['outcome'])
    assert any(x['tool']==target and x['state']=='completed' for x in r['outcome']['results']),r['outcome']
   else:
    assert not any(c['tool']=='self_battery_secret' for c in r['calls'])
    assert 'self_battery_secret' not in w.c._full_tool_harness.catalog()
    from core.utils.tool_harness.registry import manifest
    r['discovered_unregistered']=[x for x in manifest(w.c.func_handler.tool_manager) if x['name']=='self_battery_secret']
    assert r['discovered_unregistered'][0]['availability']=='unaudited_contract_or_source'
   r['passed']=True;budget.finish(charge,{'passed':True,'modes':modes})
   with out.open('a') as f:f.write(json.dumps(r,ensure_ascii=False,default=str)+'\n')
   print(json.dumps({'label':label,'modes':modes,'speech':r['speech'],'passed':True},ensure_ascii=False),flush=True)
  except Exception as exc:
   r=locals().get('r',{});r.update(passed=False,error=repr(exc));budget.finish(charge,{'passed':False,'error':repr(exc)})
   with out.open('a') as f:f.write(json.dumps(r,ensure_ascii=False,default=str)+'\n')
   raise
  finally:await w.close();provider.client.close()
asyncio.run(main())
