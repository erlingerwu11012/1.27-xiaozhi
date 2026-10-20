"""Read-only formal release status; no customer data or configuration secrets."""
import json,subprocess
from pathlib import Path
from urllib.request import urlopen
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
source=(OUT/'inspect_default_route.py').read_text().split('cfg=json.loads')[0]
exec(compile(source,'<config-read-only>','exec'))
cfg=json.loads(sql("SELECT config_json FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';"))
processes=json.loads(subprocess.run(['pm2','jlist'],capture_output=True,text=True,check=True).stdout)
result={'production_commit':subprocess.run(['git','-C',str(prod),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip(),
        'tracked_changes':subprocess.run(['git','-C',str(prod),'status','--porcelain','--untracked-files=no'],capture_output=True,text=True,check=True).stdout.strip(),
        'model':cfg.get('model_name'),'temperature':cfg.get('temperature'),
        'services':[{'name':p['name'],'status':p.get('pm2_env',{}).get('status')}
                    for p in processes if p['name'] in {'xiaozhi-server','manager-api','mcp-gateway'}]}
with urlopen('https://www.realecho.cn/',timeout=20) as response:result['public_http_status']=response.status
assert result['production_commit'].startswith('35236f03') and not result['tracked_changes']
assert result['model']=='qwen3.8-flash' and float(result['temperature'])==0.4
assert result['public_http_status']==200
assert len(result['services'])==3 and all(p['status']=='online' for p in result['services'])
(OUT/'complete-chat-formal-unchanged.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False))
