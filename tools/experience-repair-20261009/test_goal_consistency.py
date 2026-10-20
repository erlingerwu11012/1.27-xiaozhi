import bootstrap,asyncio,json,time
from bootstrap import stage,budget
from test_support import connection,decision,step
from stateful_device import StatefulDevice
from core.utils.tool_harness.runtime import literal_constraints,relative_requirements,Harness
async def main():
 for mode in ['render','volume','level']:
  budget.reserve('case','original-goal:'+mode)
  if mode=='render':
   q='把屏幕渲染测试模式设为spine，不重启';good=decision(step('self_screen_set_render_mode',{'mode':'spine'}));bad=good
   assert 'self_screen_set_brightness' not in Harness.write_targets(q)
  elif mode=='volume':
   q='现在把声音提一小格，就十个点';bad=decision(step('self_audio_speaker_set_volume',{'volume':0}));good=decision(step('self_audio_speaker_set_volume',{},relative=10));assert relative_requirements(q)=={'self_audio_speaker_set_volume':10}
  else:
   q='屏幕请调到第二档';bad=decision(step('self_screen_set_brightness',{},relative=1));good=decision(step('self_screen_set_brightness',{'brightness':2}));assert literal_constraints(q)=={'self_screen_set_brightness':{'brightness':2}}
  ds=iter([bad,good]);c,m,h=connection(StatefulDevice(),lambda _:next(ds));out=await h.run(q,[])
  assert out.results[-1].state=='completed',(mode,out)
  if mode=='volume':assert m.state['volume']==60
  if mode=='level':assert m.state['level']==2
  assert len([x for x in m.calls if x['tool'].startswith('self_') and 'set_' in x['tool']])==1
 print('original goal consistency PASS',budget.report())
asyncio.run(main())
