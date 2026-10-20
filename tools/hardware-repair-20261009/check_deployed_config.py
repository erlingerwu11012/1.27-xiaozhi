from pathlib import Path
import sys,os,json,hashlib
R=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server');S=Path('/root/prjs/tmp/hardware-repair-20261009');os.chdir(R);sys.path.insert(0,str(R))
from config.config_loader import load_config,get_private_config_from_api
cfg=load_config();private=get_private_config_from_api(cfg,'ac:a7:04:fd:20:2c','ac:a7:04:fd:20:2c');merged={**cfg,**private};selected=merged['selected_module']['LLM'];llm=merged['LLM'][selected]
thinking=llm.get('enable_thinking',(llm.get('extra_body') or {}).get('enable_thinking'))
result={'selected_llm':selected,'model_name':llm.get('model_name'),'temperature':llm.get('temperature'),'enable_thinking':thinking,'hardware_billing':llm.get('hardware_billing'),'account_bound':bool(llm.get('hardware_account_id') or private.get('userId') or private.get('sys_user_id')),'persona_sha256':hashlib.sha256(str(private.get('prompt') or cfg.get('prompt') or '').encode()).hexdigest(),'local_config_sha256':hashlib.sha256((R/'data/.config.yaml').read_bytes()).hexdigest()}
assert result['model_name']=='qwen3.7-plus' and float(result['temperature'])==.4 and result['hardware_billing'] is True
assert thinking is False or str(thinking).lower()=='false'
from core.utils.voiceprint_provider import VoiceprintProvider
vp=private.get('voiceprint') or merged.get('voiceprint') or {}
provider=VoiceprintProvider(vp)
result.update(downlink_voiceprint_threshold=vp.get('similarity_threshold'),runtime_voiceprint_threshold=provider.similarity_threshold,voiceprint_enabled=provider.enabled,registered_speakers=len(provider.speaker_ids))
assert float(result['downlink_voiceprint_threshold'])==.3 and provider.similarity_threshold==.3 and provider.enabled
baseline=json.loads((S/'live-config-readonly.json').read_text())
assert all(result[k]==baseline[k] for k in ['selected_llm','model_name','temperature','enable_thinking','hardware_billing','account_bound','persona_sha256','local_config_sha256'])
result['passed']=True
(S/'live-deployed-config.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
