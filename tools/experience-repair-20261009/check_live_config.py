from pathlib import Path
import sys,os,json,hashlib
R=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server');S=Path('/root/prjs/tmp/experience-repair-20261009');os.chdir(R);sys.path.insert(0,str(R))
from config.config_loader import load_config,get_private_config_from_api
cfg=load_config();private=get_private_config_from_api(cfg,'ac:a7:04:fd:20:2c','ac:a7:04:fd:20:2c');merged={**cfg,**private};selected=merged['selected_module']['LLM'];llm=merged['LLM'][selected]
thinking=llm.get('enable_thinking',(llm.get('extra_body') or {}).get('enable_thinking'))
result={'selected_llm':selected,'model_name':llm.get('model_name'),'temperature':llm.get('temperature'),'enable_thinking':thinking,'hardware_billing':llm.get('hardware_billing'),'account_bound':bool(llm.get('hardware_account_id') or private.get('userId') or private.get('sys_user_id')),'persona_sha256':hashlib.sha256(str(private.get('prompt') or cfg.get('prompt') or '').encode()).hexdigest(),'local_config_sha256':hashlib.sha256((R/'data/.config.yaml').read_bytes()).hexdigest()}
assert result['model_name']=='qwen3.7-plus' and float(result['temperature'])==.4 and result['hardware_billing'] is True
assert thinking is False or str(thinking).lower()=='false'
(S/'live-config-readonly.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
