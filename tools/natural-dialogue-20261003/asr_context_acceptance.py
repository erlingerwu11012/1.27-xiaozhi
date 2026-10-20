"""Use saved real ASR outputs to validate continuity without new model calls."""
import json, os, sys
from pathlib import Path
from unittest.mock import MagicMock
ROOT=Path('/root/prjs/tmp/natural-dialogue-20261003/main/xiaozhi-server')
OUT=ROOT.parents[1]
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
import config.logger
config.logger.setup_logging=lambda:MagicMock()
from core.utils.operation_control import OperationControl
voice=json.loads((OUT/'live-chain-acceptance.json').read_text())['voice']
texts={c['id']:c['asr_text'] for c in voice}
c=OperationControl();first=c.begin(texts[16],('test-session','test-person'),0)
second=c.begin(texts[17],('test-session','test-person'),1)
assert first.reply=='什么时候提醒你？'
assert len(second.requests)==1 and second.requests[0].arguments=={'content':'喝水','remind_time_str':'明天上午十点'}
assert c.pending is None
c=OperationControl();c.begin(texts[16],('test-session','test-person'),0)
cancel=c.begin(texts[18],('test-session','test-person'),1)
assert not cancel.requests and c.pending is None
report={'success':True,'source':'saved real provider ASR transcripts',
        'physical_microphone_samples':0,'new_model_calls':0,'hardware_actions':0,
        'sequence':[texts[16],texts[17]],'result':second.requests[0].arguments,'cancel':texts[18]}
(OUT/'asr-context-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))
