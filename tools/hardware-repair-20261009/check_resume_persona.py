from pathlib import Path
import json,hashlib,sys,os
S=Path(__file__).parent;R=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server');os.chdir(R);sys.path.insert(0,str(R))
from config.config_loader import load_config,get_private_config_from_api
cfg=load_config();p=get_private_config_from_api(cfg,'ac:a7:04:fd:20:2c','ac:a7:04:fd:20:2c');tested=json.loads(Path('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json').read_text())
def digest(x):return hashlib.sha256(str(x).encode()).hexdigest()
result={'test_prompt_sha256':digest(tested.get('prompt')),'live_device_prompt_sha256':digest(p.get('prompt') or cfg.get('prompt')),'matched':digest(tested.get('prompt'))==digest(p.get('prompt') or cfg.get('prompt'))};(S/'resume-persona-equivalence.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
