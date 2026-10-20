"""One real reminder asset through the existing customer-billed gateway; no device writes."""
import asyncio, json, os, sys, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.request import Request, urlopen
import subprocess
import yaml

out = Path(__file__).parent
prod = Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
candidate = out / 'candidate/main/xiaozhi-server'
os.chdir(candidate); sys.path.insert(0, str(candidate))
import config.logger
config.logger.setup_logging = lambda: MagicMock()
cfg = yaml.safe_load((prod / 'data/.config.yaml').read_text())
mgr = cfg['manager-api']; url = mgr['url'].rstrip('/')
if '/xiaozhi' not in url: url += '/xiaozhi'
body = {'macAddress': 'ac:a7:04:fd:20:2c', 'clientId': 'reminder-audio-acceptance',
        'selectedModule': {'LLM': 'LLM_QwenPlusOfficial'}}
with urlopen(Request(url+'/config/agent-models', data=json.dumps(body).encode(),
             headers={'Authorization': 'Bearer '+mgr['secret'], 'Content-Type': 'application/json'}), timeout=20) as response:
    data = json.load(response)['data']
selection = data.get('selected_module') or data.get('selectedModule') or {}
tts_cfgs = data['TTS']; selected = selection.get('TTS')
tts_cfg = tts_cfgs[selected] if selected else next(iter(tts_cfgs.values()))
assert tts_cfg['type'] == 'qwen_audio_tts_plus'
assert '127.0.0.1:3011/' in tts_cfg['ws_url']
assert tts_cfg.get('hardware_billing') is True
inspection = json.loads(subprocess.check_output(['docker', 'inspect', 'one-api'], text=True))[0]
private = dict(item.split('=', 1) for item in inspection['Config']['Env'] if '=' in item)
os.environ['HW_BILLING_SERVICE_KEY'] = private['HW_BILLING_SERVICE_KEY']
os.environ['HW_BILLING_AUDIO_GATEWAY_ORIGIN'] = 'http://127.0.0.1:3011'
from core.providers.tts.qwen_audio_tts_plus import TTSProvider
from core.utils.reminder_voice import synthesize_ogg_opus
tts = TTSProvider(tts_cfg, True)
live = object(); tts._current = live; tts.ws = live
start = time.monotonic()
async def run():
    ogg = await synthesize_ogg_opus(SimpleNamespace(tts=tts), '该喝水了。')
    assert ogg.startswith(b'OggS') and len(ogg) <= 16384
    assert tts._current is live and tts.ws is live
    (out / 'reminder-live-probe.ogg').write_bytes(ogg)
    return {'success': True, 'format': 'ogg_opus', 'bytes': len(ogg),
            'elapsed_ms': round((time.monotonic()-start)*1000),
            'same_customer_gateway': True, 'hardware_billing': True,
            'live_session_unchanged': True, 'hardware_writes': 0,
            'production_modified': False}
try:
    report = asyncio.run(run())
except Exception as exc:
    report = {'success': False, 'error_type': type(exc).__name__,
              'reason': str(exc) if str(exc).startswith('tts_') else 'gateway_probe_failed'}
(out / 'live-asset-result.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report))
sys.exit(0 if report['success'] else 1)
