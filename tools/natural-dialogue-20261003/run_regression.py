"""Offline contract regressions; all outbound connections denied."""
import os
import json
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT=Path('/root/prjs/tmp/natural-dialogue-20261003/main/xiaozhi-server')
OUT=ROOT.parents[1]
os.chdir(ROOT);sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'test'))
def forbidden(*args,**kwargs):
    raise AssertionError('network forbidden in offline regression')
socket.socket.connect=forbidden
socket.socket.connect_ex=forbidden
socket.create_connection=forbidden
import config.logger
config.logger.setup_logging=lambda:MagicMock()
import config.config_loader as loader
loader.get_config_from_api=lambda config:dict(config,read_config_from_api=False)
names=['test_operation_control','test_operation_pipeline.OperationPipelineTests','test_primary_answer_direct_tts','test_prompt_pipeline_v2',
       'test_official_dialogue','test_official_tts_compiler','test_tts_subtitle',
       'test_official_params_volume','test_qwen_audio_tts_plus',
       'test_dialogue_contract_baseline.ChatBufferContractTests',
       'test_dialogue_contract_baseline.ToolMergeAndResultTests','test_mcp_initialize_identity']
suite=unittest.defaultTestLoader.loadTestsFromNames(names)
with (OUT/'regression.log').open('w') as log:
    result=unittest.TextTestRunner(verbosity=2,stream=log).run(suite)
report={'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'success':result.wasSuccessful(),'network_calls':0}
(OUT/'regression.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
if not result.wasSuccessful(): print((OUT/'regression.log').read_text()[-16000:])
sys.exit(0 if result.wasSuccessful() else 1)
