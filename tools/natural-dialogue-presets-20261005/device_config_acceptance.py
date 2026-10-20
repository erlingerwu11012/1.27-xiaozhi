"""Read authorized device config and verify a signed primary-model request; no device action."""
import hashlib,json,os,re,subprocess,sys
from pathlib import Path
from urllib.request import Request,urlopen
from unittest.mock import MagicMock
import yaml
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005');PROD=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
os.chdir(PROD);sys.path.insert(0,str(PROD))
import config.logger
config.logger.setup_logging=lambda:MagicMock()
mgr=yaml.safe_load((PROD/'data/.config.yaml').read_text())['manager-api']
url=mgr['url'].rstrip('/')
if '/xiaozhi' not in url:url+='/xiaozhi'
payload={'macAddress':'ac:a7:04:fd:20:2c','clientId':'synthetic-config-acceptance','selectedModule':{'LLM':'LLM_QwenPlusOfficial'}}
request=Request(url+'/config/agent-models',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+mgr['secret'],'Content-Type':'application/json'})
with urlopen(request,timeout=20) as response:data=json.load(response)['data']
cfg=next(value for value in data['LLM'].values() if isinstance(value,dict) and value.get('model_name'))
assert cfg['model_name']=='qwen3.8-flash' and float(cfg['temperature'])==0.4 and cfg['hardware_billing'] is True
inspection=json.loads((Path(json.loads((OUT/'deployment-receipt.json').read_text())['backup'])/'container-private.json').read_text())
private_env=dict(entry.split('=',1) for entry in inspection['Config']['Env'] if '=' in entry)
os.environ['HW_BILLING_SERVICE_KEY']=private_env['HW_BILLING_SERVICE_KEY']
os.environ['HW_BILLING_GATEWAY_ORIGIN']='http://127.0.0.1:3000'
from core.providers.llm.openai.openai import LLMProvider
provider=LLMProvider(dict(cfg,timeout=30,max_tokens=50));provider.client=provider.client.with_options(max_retries=0)
ids=[]
provider.client._client.event_hooks.setdefault('request',[]).append(lambda req:ids.append(req.headers.get('X-HW-Request-ID','')))
answer=''.join(provider.response('synthetic-owned-device',[{'role':'user','content':'17乘23是多少？只回答结果。'}]))
assert '391' in answer and ids and re.fullmatch('[a-zA-Z0-9_-]+',ids[-1])
provider.client.close()
db=yaml.safe_load((PROD.parent/'manager-api/src/main/resources/application-dev.yml').read_text())['spring']['datasource']['druid']
m=re.search(r'mysql://([^:/]+)(?::(\d+))?/([^?]+)',db['url'])
env=dict(os.environ,MYSQL_PWD=str(db['password']))
query="SELECT JSON_OBJECT('state',state,'price',price_json,'usage',usage_json) FROM one_api.hardware_billing_bill WHERE id='"+ids[-1]+"';"
p=subprocess.run(['mysql','--host='+m[1],'--port='+(m[2]or'3306'),'--user='+str(db['username']),'--batch','--raw','--skip-column-names',m[3]],input=query,env=env,capture_output=True,text=True,timeout=15)
assert p.returncode==0 and p.stdout.strip(),'meter_query_failed'
bill=json.loads(p.stdout)
assert bill['state']=='settled','signed_bill_not_settled'
report={'device_mac':payload['macAddress'],'model':cfg['model_name'],'temperature':cfg['temperature'],'owned_token_and_service_signature':True,'real_gateway_reply':answer,'bill_state':bill['state'],'usage':json.loads(bill['usage']),'hardware_actions':0,'persona_sent_to_model':False}
(OUT/'device-config-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))
