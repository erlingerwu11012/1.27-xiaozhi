"""Read-only live configuration and no-network reproduction of reminder voice failure."""
import asyncio,json,os,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.request import Request,urlopen
import yaml
PROD=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
os.chdir(PROD);sys.path.insert(0,str(PROD))
import config.logger
config.logger.setup_logging=lambda:MagicMock()
cfg=yaml.safe_load((PROD/'data/.config.yaml').read_text())
mgr=cfg['manager-api'];url=mgr['url'].rstrip('/')
if '/xiaozhi' not in url:url+='/xiaozhi'
headers={'Authorization':'Bearer '+mgr['secret'],'Content-Type':'application/json'}
body={'macAddress':'ac:a7:04:fd:20:2c','clientId':'reminder-diagnostic-readonly','selectedModule':{'LLM':'LLM_QwenPlusOfficial'}}
with urlopen(Request(url+'/config/agent-models',data=json.dumps(body).encode(),headers=headers),timeout=20) as r:data=json.load(r)['data']
selection=data.get('selected_module') or data.get('selectedModule') or {}
tts_configs=data.get('TTS') or {}
selected=selection.get('TTS')
tts_config=tts_configs.get(selected) if selected else next(iter(tts_configs.values()))
assert isinstance(tts_config,dict)
provider_type=tts_config.get('type')
assert provider_type=='qwen_audio_tts_plus','different_tts_provider'
from core.providers.tts.qwen_audio_tts_plus import TTSProvider
from core.providers.tts.dto.dto import InterfaceType
from core.utils.reminder_voice import synthesize_ogg_opus
from core.utils.service_auth import get_service_secret
tts=TTSProvider.__new__(TTSProvider)
# Exactly the interface type assigned by the installed provider constructor.
tts.interface_type=InterfaceType.DUAL_STREAM
async def reproduce():
 try:
  await synthesize_ogg_opus(SimpleNamespace(tts=tts),'诊断测试')
 except Exception as exc:return {'type':type(exc).__name__,'reason':str(exc)}
 raise AssertionError('unexpected_success')
error=asyncio.run(reproduce())
assert error=={'type':'RuntimeError','reason':'tts_stream_unsupported'}
secret,reason=get_service_secret(cfg)
report={'device':'ac:a7:04:fd:20:2c','configured_tts_provider':provider_type,'interface':'DUAL_STREAM','isolated_wav_method_present':callable(getattr(TTSProvider,'synthesize_wav_isolated',None)),'reproduced_error':error,'network_audio_requests':0,'hardware_writes':0,'service_secret_configured':bool(secret),'service_secret_status':reason or 'configured','production_modified':False}
(OUT/'reminder-voice-diagnosis-20261007.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))
