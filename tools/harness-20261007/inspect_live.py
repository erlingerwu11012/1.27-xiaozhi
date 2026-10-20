import asyncio,json,os,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
import yaml
root=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server');stage=Path('/root/prjs/tmp/harness-20261007')
sys.path.insert(0,str(root))
import config.config_loader
config.config_loader.get_config_from_api=lambda c:dict(c,read_config_from_api=False)
import config.settings
config.settings.config_file_valid=True
import config.logger
config.logger.setup_logging=lambda:MagicMock()
from config.manage_api_client import init_service,get_server_config,get_agent_models,get_device_config
private=yaml.safe_load((root/'data/.config.yaml').read_text());init_service(private)
base=get_server_config();models=get_agent_models('ac:a7:04:fd:20:2c','harness-inspection',base.get('selected_module',{}))
cfg={**base,**models}; selected=cfg['selected_module']['LLM'];llm=cfg['LLM'][selected]
intent=cfg.get('Intent',{}).get(cfg['selected_module'].get('Intent'),{}).get('functions',[])
(stage/'private-backup/runtime-config.json').write_text(json.dumps(cfg,ensure_ascii=False));os.chmod(stage/'private-backup/runtime-config.json',0o600)
from plugins_func.loadplugins import auto_import_modules
from core.providers.tools.server_plugins.plugin_executor import ServerPluginExecutor
from core.providers.tools.server_mcp.mcp_client import ServerMCPClient
auto_import_modules('plugins_func.functions')
async def main():
 device=await get_device_config('ac:a7:04:fd:20:2c')
 (stage/'private-backup/device-config.json').write_text(json.dumps(device));os.chmod(stage/'private-backup/device-config.json',0o600)
 definitions=ServerPluginExecutor(SimpleNamespace(config=cfg,memory=SimpleNamespace(personal=True))).get_tools()
 rows=[dict(t.description,source='server_plugin') for t in definitions.values()]
 settings=json.loads((root/'data/.mcp_server_settings.json').read_text())['mcpServers']
 for name,s in settings.items():
  if s.get('disabled',False):continue
  client=ServerMCPClient(s)
  try:
   await asyncio.wait_for(client.initialize(),25)
   rows.extend(dict(t,source='server_mcp') for t in client.get_available_tools())
  finally:await client.cleanup()
 (stage/'server-catalog.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
 print(json.dumps({'model':llm.get('model_name'),'temperature':llm.get('temperature'),'hardware_billing':bool(llm.get('hardware_billing')),'intent_functions':intent,'server_tools':[r['function']['name'] for r in rows]},ensure_ascii=False))
asyncio.run(main())
