"""Read only authorized device personality, live presets and effective prompt assembly."""
import hashlib,json,os,re,sys
from pathlib import Path
from urllib.request import Request,urlopen
from unittest.mock import MagicMock
import yaml
PROD=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
os.chdir(PROD);sys.path.insert(0,str(PROD))
import config.logger
config.logger.setup_logging=lambda:MagicMock()
mgr=yaml.safe_load((PROD/'data/.config.yaml').read_text())['manager-api']
url=mgr['url'].rstrip('/')
if '/xiaozhi' not in url:url+='/xiaozhi'
headers={'Authorization':'Bearer '+mgr['secret'],'Content-Type':'application/json'}
with urlopen(Request(url+'/config/agent-models',data=json.dumps({'macAddress':'ac:a7:04:fd:20:2c','clientId':'persona-readonly-inventory','selectedModule':{'LLM':'LLM_QwenPlusOfficial'}}).encode(),headers=headers),timeout=20) as response:
 data=json.load(response)['data']
with urlopen(Request(url+'/config/server-base',data=b'{}',headers=headers),timeout=20) as response:base=json.load(response)['data']
cfg=next(v for v in data['LLM'].values() if isinstance(v,dict) and v.get('model_name'))
from core.utils.prompt_manager import PromptManager,V2_PLATFORM_TEMPLATE_PATH
persona=data.get('prompt','')
assert isinstance(persona,str) and persona.strip()
actual=PromptManager(dict(base,**data),logger=MagicMock()).build_enhanced_prompt_v2(persona,'persona-readonly-inventory',device_name=data.get('device_name','小智'),user_nickname=data.get('user_nickname','用户'),official_enhanced=True)
src=(PROD.parent/'manager-web/src/constants/personaPresets.js').read_text()
presets=[dict(zip(['id','name','description','prompt'],m)) for m in re.findall(r"\{ id: '([^']+)', name: '([^']+)', description: '([^']+)',\s*prompt: '([^']+)' \}",src)]
assert len(presets)==6
report={'device_mac':'ac:a7:04:fd:20:2c','device_name':data.get('device_name'),'user_nickname':data.get('user_nickname'),'current_persona':persona,'matching_preset':next((p['id'] for p in presets if p['prompt']==persona.strip()),None),'presets':presets,'model':{k:cfg.get(k) for k in ['model_name','base_url','temperature','max_tokens','timeout','enable_thinking','preserve_thinking','hardware_billing']},'effective_system_prompt':actual,'effective_system_sha256':hashlib.sha256(actual.encode()).hexdigest(),'platform_template':Path(V2_PLATFORM_TEMPLATE_PATH).read_text(),'config_top_level_keys':sorted(data),'conversation_validation':data.get('conversation_validation',base.get('conversation_validation'))}
(OUT/'persona-inventory-20261007.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:report[k] for k in ['device_name','user_nickname','current_persona','matching_preset','model','config_top_level_keys','conversation_validation']},ensure_ascii=False))
