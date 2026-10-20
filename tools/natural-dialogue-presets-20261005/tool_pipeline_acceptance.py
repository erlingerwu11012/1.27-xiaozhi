"""Replay all real native proposals through actual routing/validation and isolated transport."""
import asyncio,json,os,sys
from pathlib import Path
from unittest.mock import MagicMock
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
ROOT=OUT/'worktree/main/xiaozhi-server'
os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'test')]
import config.logger
config.logger.setup_logging=lambda:MagicMock()
from test_operation_control import fixture
from core.utils.operation_control import get_control,execute_plan
results=[]
async def main():
 for row in json.loads((OUT/'release-acceptance.json').read_text())['tool_probes']:
  conn,manager,executor=fixture()
  control=get_control(conn)
  plan=control.begin(row['user'],('synthetic','actor'))
  route='primary_model_native'
  if plan.requests:
   route='bounded_explicit_request'
   await execute_plan(conn,plan)
  else:
   for proposal in row['tool_calls']:
    await manager.execute_tool(proposal['name'],json.loads(proposal['arguments']))
  actual=[name for name,args in executor.calls]
  expected=[row['expected_tool']] if row['expected_tool'] else []
  results.append({'user':row['user'],'preset':row['preset'],'route':route,'raw_native_pass':row['native_selection_pass'],'executed_calls':executor.calls,'pass':actual==expected})
asyncio.run(main())
report={'real_model_proposals':True,'real_routing_and_validation':True,'device_transport':'isolated fixture; no hardware writes','cases':results,'passed':sum(r['pass'] for r in results),'total':len(results),'success':all(r['pass'] for r in results)}
(OUT/'tool-pipeline-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({key:report[key] for key in ['passed','total','success']}))
assert report['success']
