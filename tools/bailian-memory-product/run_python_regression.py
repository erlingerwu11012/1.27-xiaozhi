"""Offline provider and audio regressions, isolated module processes."""
import json
import subprocess
from pathlib import Path

candidate=Path('/root/prjs/tmp/bailian-memory-product/main/xiaozhi-server')
modules=['test_camera_mcp_tools','test_mcp_initialize_identity','test_predeploy_asr_guards','test_dialogue_contract_baseline','test_official_dialogue']
results=[]
for module in modules:
    code="import sys;sys.path.insert(0,'test');from unittest.mock import MagicMock;import config.logger as l;l.setup_logging=MagicMock(return_value=MagicMock());import unittest;unittest.main(module='"+module+"',verbosity=2)"
    log='/tmp/bailian-memory-regression-'+module+'.log'
    with open(log,'w') as output:
        result=subprocess.run(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python','-c',code],cwd=candidate,stdout=output,stderr=subprocess.STDOUT,timeout=120)
    results.append({'module':module,'exit':result.returncode,'log':log})
    print(json.dumps(results[-1]),flush=True)
    if result.returncode:print(Path(log).read_text()[-3500:],flush=True)
Path('/tmp/bailian-memory-python-regression-result.json').write_text(json.dumps(results,indent=2))
raise SystemExit(any(row['exit'] for row in results))
