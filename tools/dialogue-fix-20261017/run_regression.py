"""Run the isolated server regression suite, without production configuration."""
import json,os,sys,unittest
from pathlib import Path
from unittest.mock import MagicMock

stage=Path(__file__).resolve().parent
os.chdir(stage/'candidate')
sys.path[:0]=[str(Path.cwd()),str(Path.cwd()/'test')]
import test_harness_repair_20261017,config
config.logger.build_module_string=lambda *a,**k:'test'
config.logger.create_connection_logger=lambda *a,**k:MagicMock()
names=['test_dialogue_fix_20261017','test_experience_20261017','test_harness_repair_20261017',
       'test_operation_control','test_unified_recipient_outbound','test_person_memory_identity',
       'test_person_memory_tools','test_tts_subtitle','test_tts_listen_observe','test_tts_sentence_telemetry']
with (stage/'regression.log').open('w',encoding='utf-8') as output:
    result=unittest.TextTestRunner(stream=output,verbosity=2).run(unittest.TestSuite(
        unittest.defaultTestLoader.loadTestsFromName(name) for name in names))
summary={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped)}
(stage/'verification.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary))
sys.exit(0 if result.wasSuccessful() else 1)
