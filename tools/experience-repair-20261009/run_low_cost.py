import bootstrap,contextlib,io,json,sys,unittest
from pathlib import Path
from bootstrap import budget,stage,work
class IsolatedPaths(list):
    def insert(self,index,value):
        if Path(value).resolve()==Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server'):return
        super().insert(index,value)
sys.path=IsolatedPaths(sys.path);sys.path.insert(0,str(work/'test'))
class Result(unittest.TextTestResult):
    def startTest(self,test):budget.reserve('case',test.id());super().startTest(test)
old=unittest.TestCase.subTest
@contextlib.contextmanager
def counted(self,*args,**kwargs):
    budget.reserve('case',self.id()+':subtest')
    with old(self,*args,**kwargs):yield
unittest.TestCase.subTest=counted
names=['test_unit','test_protocol','test_operation_control','test_operation_pipeline','test_verified_tool_facts','test_natural_tool_failure_regression','test_device_reminder','test_card_action','test_reminder_control','test_reminder_card_converge','test_reminder_reliability','test_person_memory_identity','test_person_memory_tools','test_identity_snapshot_request','test_recipient_resolver','test_unified_recipient_outbound','test_multi_device_isolation','test_websocket_session','test_primary_answer_direct_tts','test_tts_subtitle','test_reminder_voice_abort','test_interaction_renewal','test_vision_capability']
log=io.StringIO()
with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
    r=unittest.TextTestRunner(stream=log,resultclass=Result,verbosity=1).run(unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names))
(stage/'low-cost.log').write_text(log.getvalue(),encoding='utf-8')
summary={'tests':r.testsRun,'failures':[(str(t),s[-1800:]) for t,s in r.failures],'errors':[(str(t),s[-1800:]) for t,s in r.errors],'skipped':[(str(t),s) for t,s in r.skipped],'budget':budget.report()}
(stage/'low-cost-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False));raise SystemExit(not r.wasSuccessful())
