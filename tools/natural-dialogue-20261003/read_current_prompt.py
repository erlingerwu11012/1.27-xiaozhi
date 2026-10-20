"""Read current production rules; render with an explicitly labelled example persona."""
import json, os, sys, subprocess
from pathlib import Path
from unittest.mock import MagicMock
ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
processes=json.loads(subprocess.run(['pm2','jlist'],check=True,capture_output=True,text=True).stdout)
process=next(p for p in processes if p['name']=='xiaozhi-server')
runtime=Path('/proc/'+str(process['pid'])+'/environ').read_bytes().split(b'\0')
for entry in runtime:
    if entry.startswith(b'AGENT_PERSONAS_DIR='):
        os.environ['AGENT_PERSONAS_DIR']=entry.split(b'=',1)[1].decode()
import config.logger
config.logger.setup_logging=lambda:MagicMock()
from config.settings import load_config
from core.utils.prompt_manager import PromptManager, CAMERA_ROUTING_INSTRUCTION
from core.providers.tts.official.prompt import OFFICIAL_EXPRESSION_CONSTRAINT
cfg=load_config()
persona='你腹黑、调皮、爱捉弄人。说话带一点坏心眼，喜欢调侃用户，但本质是善意的玩笑。'
snapshot=PromptManager(cfg,logger=MagicMock()).build_enhanced_prompt_v2(
    persona,'read-only-example',device_name='{用户设置的助手名字}',official_enhanced=True)
data={'base':cfg.get('system_base_prompt',''),'camera':CAMERA_ROUTING_INSTRUCTION.strip(),
      'official':OFFICIAL_EXPRESSION_CONSTRAINT.strip(),'example_snapshot':snapshot,
      'uses_example_persona':True,'reads_live_device_history':False}
(OUT/'current-prompt-layers.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
(OUT/'current-prompt-example.txt').write_text(snapshot)
print(json.dumps({'base':data['base'],'camera':data['camera'],'official':data['official'],
                 'skills_environment_present':bool(os.environ.get('AGENT_PERSONAS_DIR'))},ensure_ascii=False))
