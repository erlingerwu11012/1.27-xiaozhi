import sys,os,json,asyncio,types
from pathlib import Path
from unittest.mock import MagicMock,patch
root=Path(os.environ.get('MCP_PRUNE_TEST_ROOT','/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server'));os.chdir(root);sys.path.insert(0,str(root))
import config.logger
config.logger.setup_logging=lambda:MagicMock()
from core.providers.tools.unified_tool_manager import ToolManager
from core.providers.tools.base import ToolType,ToolDefinition
from core.providers.tools.retired_tools import RETIRED_TOOL_NAMES,is_retired_tool
from core.providers.tools.device_mcp.mcp_handler import call_mcp_tool
names=sorted(RETIRED_TOOL_NAMES);kept=['self_get_device_status','self_audio_speaker_set_volume','self_screen_set_brightness','alarm_set','memory_search']
class Executor:
 def get_tools(self):return {n:ToolDefinition(n,{'type':'function','function':{'name':n,'parameters':{'type':'object','properties':{}}}},ToolType.DEVICE_MCP) for n in names+kept}
 async def execute(self,*a):raise AssertionError('Retired tool reached executor')
async def main():
 m=ToolManager(types.SimpleNamespace(config={}));m.register_executor(ToolType.DEVICE_MCP,Executor());checks=0
 for n in names:
  assert n not in m.get_all_tools() and not m.has_tool(n) and m.resolve_tool_name(n) is None;checks+=1
 assert set(m.get_supported_tool_names())==set(kept);checks+=1
 assert {x['function']['name'] for x in m.get_function_descriptions()}==set(kept);checks+=1
 m.refresh_tools();assert set(m.get_all_tools())==set(kept);checks+=1
 assert sum(m.get_tool_statistics().values())==len(kept);checks+=1
 raw=['self.get_system_info','self.reboot','self.screen.get_info','self.screen.set_render_mode','self.screen.set_render_options','self.screen.get_render_status']
 for n in names+raw:
  assert is_retired_tool(n);assert m.resolve_tool_name(n) is None
  for enabled in [False,True]:
   with patch('core.utils.operation_control.enabled',return_value=enabled):
    r=await m.execute_tool(n,{})
    assert '没有执行' in (r.response or '') or '停用' in (r.response or '')
   checks+=1
  r=await m._execute_tool(n,{});assert '停用' in r.response;checks+=1
  try:await call_mcp_tool(None,None,n)
  except ValueError as e:assert '停用' in str(e)
  else:raise AssertionError('Raw MCP was not denied')
  checks+=1
 for n in kept:assert not is_retired_tool(n) and m.has_tool(n);checks+=1
 result={'passed':True,'checks':checks,'retired_public_names':names,'kept_samples':kept,'tested_root':str(root),'paid_model_requests':0,'firmware_compiled':False}
 Path('/root/prjs/tmp/mcp-prune-20261010/test-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
asyncio.run(main())
