import bootstrap,asyncio,json
from bootstrap import budget,stage
from test_support import connection,decision,step
from stateful_device import StatefulDevice
from core.utils.tool_harness.runtime import relative_requirements,quoted_note_request
async def main():
 rows=[]
 for delta in [-1,-10]:
  budget.reserve('case','relative-extra-reference:'+str(delta))
  c,m,h=connection(StatefulDevice(),lambda _:decision(step('self_screen_set_brightness',{'$ref':{'step':'fake','path':'wrong'}},relative=delta)))
  out=await h.run('屏幕太刺眼，帮我往下调一档',[])
  assert m.state['level']==2,(out,m.calls);assert out.results[-1].state=='completed';rows.append({'delta':delta,'speech':out.reply})
 for q,expected in [('替我记条便签：明天带书',True),('上次你说替我记条便签：明天带书',False)]:
  budget.reserve('case','quoted-note-boundary');assert bool(quoted_note_request(q))==expected
 for q in ['屏幕太刺眼，帮我往下调一档','亮度往下调一档']:
  budget.reserve('case','relative-original-constraint');assert relative_requirements(q)=={'self_screen_set_brightness':-1}
 (stage/'relative-canonical-results.json').write_text(json.dumps(rows,ensure_ascii=False));print('relative normalization PASS',budget.report())
asyncio.run(main())
