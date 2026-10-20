import json,os,sys
from pathlib import Path
from unittest.mock import MagicMock
stage=Path(__file__).parent;work=stage/'work';sys.path.insert(0,str(work));os.chdir(work)
import config.config_loader
config.config_loader.get_config_from_api=lambda c:dict(c,read_config_from_api=False)
import config.settings
config.settings.config_file_valid=True
import config.logger
config.logger.setup_logging=lambda:MagicMock()
def production_provider():
    import subprocess
    # Load only existing service-signing variables in memory. Do not print them.
    pid=subprocess.check_output(['pm2','pid','xiaozhi-server'],text=True).strip().splitlines()[-1]
    for field in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0'):
        key,sep,value=field.partition(b'=')
        if key.decode(errors='ignore') in {'HW_BILLING_SERVICE_KEY','HW_BILLING_GATEWAY_ORIGIN'} and sep:os.environ[key.decode()]=value.decode()
    cfg=json.loads((stage/'private-backup/runtime-config.json').read_text())
    llm=dict(cfg['LLM'][cfg['selected_module']['LLM']])
    if not llm.get('hardware_account_id'):
        device=json.loads((stage/'private-backup/device-config.json').read_text())
        llm['hardware_account_id']=str(device.get('userId') or device.get('user_id') or cfg.get('sys_user_id') or '')
    assert llm['model_name']=='qwen3.7-plus' and float(llm['temperature'])==.4 and llm.get('hardware_billing')
    from core.providers.llm.openai.openai import LLMProvider
    provider=LLMProvider(llm)
    from budget_guard import attach
    attach(provider)
    return provider,cfg
def system_prompt(cfg):
    from core.utils.prompt_manager import PromptManager
    return PromptManager(cfg,MagicMock()).build_enhanced_prompt_v2(cfg.get('prompt',''),'SIMULATION-NO-HARDWARE',None,device_name=cfg.get('device_custom_name','小智'),official_enhanced=True)
