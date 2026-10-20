from pathlib import Path
import json,sys,os,importlib.util
from urllib.parse import urlparse
S=Path(__file__).parent;R=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
spec=importlib.util.spec_from_file_location('release',S/'release.py');rel=importlib.util.module_from_spec(spec);spec.loader.exec_module(rel)
state=json.loads((rel.REL/'deployment-state.json').read_text());env=rel.env_of(rel.app(state['new']['xiaozhi-server']))
for k in ['HW_BILLING_SERVICE_KEY','HW_BILLING_GATEWAY_ORIGIN','HW_BILLING_AUDIO_GATEWAY_ORIGIN']:
 if k in env:os.environ[k]=env[k]
os.chdir(R);sys.path.insert(0,str(R))
from config.config_loader import load_config,get_private_config_from_api
c=load_config();p=get_private_config_from_api(c,'ac:a7:04:fd:20:2c','ac:a7:04:fd:20:2c');m={**c,**p};cfg=m['LLM'][m['selected_module']['LLM']]
from core.providers.llm.openai.openai import LLMProvider
provider=LLMProvider(cfg);u=urlparse(str(provider.client.base_url));assert not u.username and not u.password and not u.query
result={'passed':True,'model_name':cfg['model_name'],'hardware_billing':cfg['hardware_billing'],'account_bound':bool(cfg.get('hardware_account_id')),'client_base_url':u.geturl(),'local_one_api_port_3000':u.hostname in {'127.0.0.1','localhost'} and u.port==3000,'paid_test_reported_model':'qwen3.7-plus','new_paid_calls':0}
assert result['local_one_api_port_3000'] and result['hardware_billing'] and result['account_bound']
provider.client.close();(S/'live-model-route.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
