import asyncio,hashlib,json,os,sys
from pathlib import Path
from unittest.mock import MagicMock
import yaml
stage=Path(__file__).parent;root=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
sys.path.insert(0,str(root))
import config.config_loader
config.config_loader.get_config_from_api=lambda c:dict(c,read_config_from_api=False)
import config.settings
config.settings.config_file_valid=True
import config.logger
config.logger.setup_logging=lambda:MagicMock()
from config.manage_api_client import init_service,get_server_config,get_agent_models
private=yaml.safe_load((root/'data/.config.yaml').read_text());init_service(private)
base=get_server_config();models=get_agent_models('ac:a7:04:fd:20:2c','harness-readonly-audit',base.get('selected_module',{}))
cfg={**base,**models};llm=cfg['LLM'][cfg['selected_module']['LLM']]
old=json.loads((stage/'private-backup/runtime-config.json').read_text())
old_llm=old['LLM'][old['selected_module']['LLM']]
baseline=json.loads((stage/'baseline.json').read_text())
modified=['core/connection.py','core/providers/llm/openai/openai.py','config/config_loader.py']
report={'model':llm.get('model_name'),'temperature':llm.get('temperature'),'hardware_billing':bool(llm.get('hardware_billing')),
 'persona_unchanged':cfg.get('prompt')==old.get('prompt'),
 'gateway_config_unchanged':all(llm.get(k)==old_llm.get(k) for k in ['base_url','url','api_key','hardware_billing','provider_type']),
 'gateway_url':llm.get('base_url') or llm.get('url'),
 'official_provider_selection_unchanged':cfg.get('selected_module',{}).get('LLM')==old.get('selected_module',{}).get('LLM'),
 'source_drift':{p:hashlib.sha256((root/p).read_bytes()).hexdigest()!=baseline[p] for p in modified},
 'timestamp':__import__('datetime').datetime.now().isoformat(),
 'production_entrypoints':[]}
import subprocess
pid=subprocess.check_output(['pm2','pid','xiaozhi-server'],text=True).strip().splitlines()[-1]
report['production_entrypoints']=[x.decode() for x in Path('/proc/'+pid+'/cmdline').read_bytes().split(b'\0') if x.endswith(b'.py')]
(stage/'live-readonly-audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
