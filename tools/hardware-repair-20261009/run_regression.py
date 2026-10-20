import bootstrap,contextlib,io,json,sys,unittest
from pathlib import Path
from bootstrap import budget,stage,work
sys.path.insert(0,str(work/'test'))
class Result(unittest.TextTestResult):
 def startTest(self,test):budget.reserve('case',test.id());super().startTest(test)
names=['test_operation_control','test_verified_tool_facts','test_natural_tool_failure_regression','test_identity_snapshot_request','test_recipient_resolver','test_unified_recipient_outbound','test_multi_device_isolation','test_websocket_session','test_primary_answer_direct_tts','test_tts_subtitle','test_reminder_voice_abort','test_interaction_renewal','test_vision_capability','test_person_memory_identity','test_person_memory_tools']
log=io.StringIO()
with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
 r=unittest.TextTestRunner(stream=log,resultclass=Result,verbosity=2).run(unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names))
(stage/'regression.log').write_text(log.getvalue())
summary={'tests':r.testsRun,'failures':[(str(t),s[-2200:]) for t,s in r.failures],'errors':[(str(t),s[-2200:]) for t,s in r.errors],'skipped':[(str(t),s) for t,s in r.skipped],'budget':budget.report()}
(stage/'regression-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False));raise SystemExit(not r.wasSuccessful())
