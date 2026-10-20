import json,os,re,subprocess
from pathlib import Path
import yaml
prod=Path('/root/prjs/xiaozhi-esp32-server')
db=yaml.safe_load((prod/'main/manager-api/src/main/resources/application-dev.yml').read_text())['spring']['datasource']['druid']
m=re.search(r'mysql://([^:/]+)(?::(\d+))?/([^?]+)',db['url'])
env=dict(os.environ,MYSQL_PWD=str(db['password']))
def sql(q):
 p=subprocess.run(['mysql','--host='+m[1],'--port='+(m[2]or'3306'),'--user='+str(db['username']),'--batch','--raw','--skip-column-names',m[3]],input=q,env=env,capture_output=True,text=True,timeout=15)
 assert p.returncode==0
 return p.stdout.strip()
cfg=json.loads(sql("SELECT config_json FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';"))
key=cfg['api_key'].removeprefix('sk-');assert re.fullmatch('[a-zA-Z0-9_-]+',key)
info=sql("SELECT JSON_OBJECT('group',u.`group`,'has_flash',FIND_IN_SET('qwen3.8-flash',COALESCE(t.models,''))) FROM one_api.tokens t JOIN one_api.users u ON u.id=t.user_id WHERE t.`key`='"+key+"';")
print(info)
print(sql("SELECT JSON_OBJECT('channel2_type',a.type,'same_upstream_credential',a.`key`=b.`key`) FROM one_api.channels a JOIN one_api.channels b ON b.id=8 WHERE a.id=2;"))
