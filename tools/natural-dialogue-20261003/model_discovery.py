import json, os, re, subprocess
from pathlib import Path
from urllib.parse import urlparse
import yaml
from openai import OpenAI

ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
db=yaml.safe_load((ROOT.parent/'manager-api/src/main/resources/application-dev.yml').read_text())['spring']['datasource']['druid']
match=re.search(r'mysql://([^:/]+)(?::(\d+))?/([^?]+)',db['url'])
env=dict(os.environ,MYSQL_PWD=str(db['password']))
def sql(query):
    p=subprocess.run(['mysql','--host='+match[1],'--port='+(match[2]or'3306'),'--user='+str(db['username']),'--batch','--raw','--skip-column-names',match[3]],input=query,env=env,capture_output=True,text=True,timeout=15)
    if p.returncode: raise RuntimeError('database_query_failed')
    return p.stdout.strip()
config=json.loads(sql("SELECT config_json FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';"))
base=config.get('base_url') or config.get('url')
client=OpenAI(api_key=config['api_key'],base_url=base,max_retries=0,timeout=20)
print(json.dumps({'configured_model':config.get('model_name'),'gateway_host':urlparse(base).hostname}),flush=True)
try:
    ids=[m.id for m in client.models.list().data if 'qwen' in m.id.lower()]
    print(json.dumps({'available_qwen_ids':ids}),flush=True)
except Exception as e:
    print(json.dumps({'models_list_error':type(e).__name__,'http_status':getattr(e,'status_code',None)}),flush=True)
print(json.dumps({'channel_columns':sql('SHOW COLUMNS FROM one_api.channels;').splitlines()}),flush=True)
print(json.dumps({'qwen_channels':sql("SELECT id,name,type,base_url,models FROM one_api.channels WHERE models LIKE '%qwen%';").splitlines()}),flush=True)
