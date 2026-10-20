"""Read-only inventory; credentials never leave server memory."""
import hashlib,json,os,re,subprocess
from pathlib import Path
import yaml
PROD=Path('/root/prjs/xiaozhi-esp32-server');OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
spring=yaml.safe_load((PROD/'main/manager-api/src/main/resources/application-dev.yml').read_text())['spring']
db=spring['datasource']['druid'];match=re.search(r'mysql://([^:/]+)(?::(\d+))?/([^?]+)',db['url'])
def sql(q):
 p=subprocess.run(['mysql','--host='+match[1],'--port='+(match[2]or'3306'),'--user='+str(db['username']),'--batch','--raw','--skip-column-names',match[3]],input=q,capture_output=True,text=True,env=dict(os.environ,MYSQL_PWD=str(db['password'])),timeout=15)
 if p.returncode:raise RuntimeError('database_inventory_failed')
 return p.stdout.strip()
def jrows(q):return [json.loads(line) for line in sql(q).splitlines() if line]
cfg=json.loads(sql("SELECT config_json FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';"))
token=str(cfg['api_key']).removeprefix('sk-');assert re.fullmatch('[A-Za-z0-9_-]+',token)
processes=json.loads(subprocess.check_output(['pm2','jlist'],text=True))
inspection={
 'model':{k:cfg.get(k) for k in ['model_name','base_url','temperature','max_tokens','enable_thinking','preserve_thinking','thinking_budget']},
 'channels':jrows("SELECT JSON_OBJECT('id',id,'name',name,'type',type,'status',status,'models',models,'group',`group`,'base_url',base_url,'priority',priority) FROM one_api.channels ORDER BY id;"),
 'token':jrows("SELECT JSON_OBJECT('id',id,'user_id',user_id,'models',models) FROM one_api.tokens WHERE `key`='"+token+"';"),
 'token_schema':sql('SHOW COLUMNS FROM one_api.tokens;'),
 'abilities':jrows("SELECT JSON_OBJECT('group',`group`,'model',model,'channel_id',channel_id,'enabled',enabled,'priority',priority) FROM one_api.abilities WHERE model LIKE 'qwen3.%' ORDER BY model,channel_id;"),
 'processes':[{ 'name':p['name'],'status':p['pm2_env']['status'],'cwd':p['pm2_env'].get('pm_cwd'),'exec':p['pm2_env'].get('pm_exec_path')} for p in processes if p['name'] in {'manager-api','xiaozhi-server','mcp-gateway'}],
 'schema_models':sql('SHOW COLUMNS FROM ai_model_config;'),
 'schema_agents':sql('SHOW COLUMNS FROM ai_agent;'),
 'schema_options':sql('SHOW COLUMNS FROM one_api.options;'),
 'agent_llm_counts':sql('SELECT llm_model_id,COUNT(*) FROM ai_agent GROUP BY llm_model_id;'),
 'source_sha256':{name:hashlib.sha256((PROD/name).read_bytes()).hexdigest() for name in ['main/xiaozhi-server/core/utils/prompt_manager.py','main/xiaozhi-server/core/utils/conversation_guidance.py','main/xiaozhi-server/core/providers/llm/openai/openai.py','main/xiaozhi-server/core/utils/operation_control.py','main/xiaozhi-server/core/providers/tools/unified_tool_manager.py']}
}
(OUT/'qwen37-release-inspection-20261007.json').write_text(json.dumps(inspection,ensure_ascii=False,indent=2))
print(json.dumps(inspection,ensure_ascii=False))
