"""Run existing relevant tests against the isolated source, never production."""
import bootstrap
import contextlib,io,json,shutil,sys,unittest
from pathlib import Path

source=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/test')
target=bootstrap.work/'test'
shutil.copytree(source,target,dirs_exist_ok=True,ignore=shutil.ignore_patterns('test_account_owner_and_reminder.py','test_official_service_defaults.py'))
models=bootstrap.work/'models'
if not models.exists():models.symlink_to(source.parent/'models',target_is_directory=True)
scripts=bootstrap.work/'scripts'
if not scripts.exists():scripts.symlink_to(source.parent/'scripts',target_is_directory=True)
sys.path.insert(0,str(target))
# Some legacy tests insert the production root into sys.path. Keep imports
# isolated while still allowing their explicit read-only Java/source checks.
class IsolatedPaths(list):
    def insert(self,index,value):
        if Path(value).resolve()==source.parent.resolve():return
        super().insert(index,value)
sys.path=IsolatedPaths(sys.path)
names=['test_predeploy_asr_guards','test_operation_control','test_operation_pipeline',
       'test_verified_tool_facts','test_natural_tool_failure_regression',
       'test_device_reminder','test_card_action','test_reminder_control',
       'test_reminder_card_converge','test_reminder_reliability',
       'test_person_memory_identity','test_person_memory_tools',
       'test_identity_snapshot_request','test_account_owner_and_reminder',
       'test_recipient_resolver','test_unified_recipient_outbound',
       'test_multi_device_isolation','test_websocket_session',
       'test_prompt_pipeline_v2','test_conversation_contract',
       'test_primary_answer_direct_tts','test_tts_subtitle',
       'test_official_service_defaults','test_hardware_billing_proof',
       'test_face_enrollment_contract','test_reminder_voice_abort',
       'test_habit_sync','test_habit_sync_api','test_interaction_renewal']
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names)
log=io.StringIO()
with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
    result=unittest.TextTestRunner(verbosity=1,stream=log).run(suite)
(bootstrap.stage/'regression-output.txt').write_text(log.getvalue(),encoding='utf8')
summary={'tests':result.testsRun,'failures':[(str(t),s[-1600:]) for t,s in result.failures],
         'errors':[(str(t),s[-1600:]) for t,s in result.errors]}
(bootstrap.stage/'regression-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(summary,ensure_ascii=False))
sys.exit(0 if result.wasSuccessful() else 1)
