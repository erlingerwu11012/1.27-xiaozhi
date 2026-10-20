import json,os,sys,subprocess
from pathlib import Path
from unittest.mock import MagicMock
stage=Path(__file__).resolve().parent;work=Path(os.environ.get('CANDIDATE_WORK',str(stage/'work')))
os.environ['EXPERIENCE_TEST_BUDGET']=str(stage/'budget.sqlite3')
os.environ['HARNESS_LEDGER_PATH']=str(stage/'work/data/test-operations.sqlite3')
os.environ['PERSON_MATERIAL_OUTBOX']=str(stage/'work/data/test-material-outbox.sqlite3')
sys.path.insert(0,str(work));sys.path.append('/root/prjs/tmp/harness-20261007');os.chdir(work)
import config.config_loader
config.config_loader.get_config_from_api=lambda c:dict(c,read_config_from_api=False)
import config.settings
config.settings.config_file_valid=True
import config.logger
config.logger.setup_logging=lambda:MagicMock()
from budget import Budget
budget=Budget()

def production_provider():
    pid=subprocess.check_output(['pm2','pid','xiaozhi-server'],text=True).strip().splitlines()[-1]
    for field in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0'):
        key,sep,value=field.partition(b'=')
        if sep and key.decode(errors='ignore') in {'HW_BILLING_SERVICE_KEY','HW_BILLING_GATEWAY_ORIGIN','HW_BILLING_AUDIO_GATEWAY_ORIGIN'}:os.environ[key.decode()]=value.decode()
    private=Path('/root/prjs/tmp/harness-20261007/private-backup')
    cfg=json.loads((private/'runtime-config.json').read_text());llm=dict(cfg['LLM'][cfg['selected_module']['LLM']])
    if not llm.get('hardware_account_id'):
        device=json.loads((private/'device-config.json').read_text());llm['hardware_account_id']=str(device.get('userId') or device.get('user_id') or cfg.get('sys_user_id') or '')
    persona_device_config=json.loads((private/'device-config.json').read_text())
    for key in ('prompt','device_custom_name'):
        if persona_device_config.get(key):cfg[key]=persona_device_config[key]
    assert llm['model_name']=='qwen3.7-plus' and float(llm['temperature'])==.4 and llm.get('hardware_billing')
    from core.providers.llm.openai.openai import LLMProvider
    provider=LLMProvider(llm)
    def before(request):
        if '/chat/completions' not in request.url.path:raise RuntimeError('unexpected_paid_endpoint')
        request.extensions['experience_charge']=budget.reserve('model','qwen3.7-plus')
    def after(response):
        if 'text/event-stream' in response.headers.get('content-type',''):
            budget.finish(response.request.extensions['experience_charge'],{'status':response.status_code,'stream':True,'usage':'recorded_after_stream_completion'})
            return
        response.read()
        try:
            data=response.json();meta={'status':response.status_code,'model':data.get('model'),'usage':data.get('usage'),'id':data.get('id')}
        except ValueError:meta={'status':response.status_code}
        budget.finish(response.request.extensions['experience_charge'],meta)
    provider.client._client.event_hooks['request'].append(before)
    provider.client._client.event_hooks['response'].append(after)
    return provider,cfg

def system_prompt(cfg):
    from core.utils.prompt_manager import PromptManager
    return PromptManager(cfg,MagicMock()).build_enhanced_prompt_v2(cfg.get('prompt',''),'SIMULATION-NO-HARDWARE',None,device_name=cfg.get('device_custom_name','小智'),official_enhanced=True)
