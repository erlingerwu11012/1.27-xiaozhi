"""Run mock-only tests, with outbound connections denied at socket boundary."""
import os
import json
import socket
import sys
import unittest
from pathlib import Path

ROOT = Path('/root/prjs/tmp/remove-llm-rewrite-20261003/candidate')
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'test'))


def forbidden(*args, **kwargs):
    raise AssertionError('external network access forbidden in rewrite regression')


socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.create_connection = forbidden
import config.config_loader as loader
loader.get_config_from_api = lambda config: dict(config, read_config_from_api=False)

names = [
    'test_primary_answer_direct_tts',
    'test_prompt_pipeline_v2',
    'test_official_dialogue',
    'test_official_tts_compiler',
    'test_tts_subtitle',
    'test_official_params_volume',
    'test_qwen_audio_tts_plus',
    'test_dialogue_contract_baseline.ChatBufferContractTests',
    'test_dialogue_contract_baseline.ToolMergeAndResultTests',
]
suite = unittest.defaultTestLoader.loadTestsFromNames(names)
with (ROOT.parent / 'regression.log').open('w', encoding='utf-8') as log:
    result = unittest.TextTestRunner(verbosity=2, stream=log).run(suite)
report = {'run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'success': result.wasSuccessful(), 'upstream_calls': 0, 'mode': 'mock_only_outbound_connections_denied'}
(ROOT.parent / 'regression.json').write_text(json.dumps(report, indent=2) + '\n')
print('REGRESSION_RESULT', report)
if not result.wasSuccessful():
    print((ROOT.parent / 'regression.log').read_text()[-12000:])
sys.exit(0 if result.wasSuccessful() else 1)
