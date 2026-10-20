import bootstrap,json,sys,unittest,contextlib,io
from bootstrap import stage,budget,work
sys.path.insert(0,str(work/'test'))
class Result(unittest.TextTestResult):
 def startTest(self,t):budget.reserve('case',t.id());super().startTest(t)
names=['test_device_reminder','test_person_memory_recovery','test_memory_continuity','test_vision_identify','test_qwen_audio_tts_plus','test_websocket_session','test_primary_answer_direct_tts','test_tts_subtitle','test_interaction_renewal','test_card_action','test_reminder_control','test_person_memory_tools','test_reminder_card_converge']
log=io.StringIO()
with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):r=unittest.TextTestRunner(stream=log,resultclass=Result,verbosity=1).run(unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names))
(stage/'focused-regression.log').write_text(log.getvalue());result={'run':r.testsRun,'failures':[(str(t),s[-2200:]) for t,s in r.failures],'errors':[(str(t),s[-2200:]) for t,s in r.errors],'skipped':[(str(t),s) for t,s in r.skipped],'budget':budget.report()};(stage/'focused-regression-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));raise SystemExit(not r.wasSuccessful())
