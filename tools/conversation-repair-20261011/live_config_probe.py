import bootstrap,json,os
from bootstrap import production_provider,stage,budget
p,c=production_provider();p.client.close();budget.reserve('case','readonly-live-device-config')
from config.config_loader import get_private_config_from_api
from config.manage_api_client import ManageApiClient
import yaml
private=yaml.safe_load((stage/'baseline/private-config.yaml').read_text())
c['manager-api']=dict(private['manager-api'])
c['manager-api']['url']='http://127.0.0.1:18005/xiaozhi'
c['manager-api']['max_retries']=0
ManageApiClient(c)
v=get_private_config_from_api(c,'ac:a7:04:fd:20:2c','ac:a7:04:fd:20:2c');m={**c,**v}
path=stage/'live-config-private.json';path.write_text(json.dumps(m,ensure_ascii=False));path.chmod(0o600)
result={}
for kind in ['LLM','VLLM']:
 key=m['selected_module'].get(kind);f=m.get(kind,{}).get(key,{})
 result[kind]={'selection':key,'model':f.get('model_name'),'type':f.get('type'),'hardware_billing':f.get('hardware_billing'),'account_bound':bool(f.get('hardware_account_id'))}
(stage/'live-config-probe.json').write_text(json.dumps(result,indent=2));print(result)
