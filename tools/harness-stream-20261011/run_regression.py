import argparse
cli=argparse.ArgumentParser();cli.add_argument('--name',default='regression-final');cli.add_argument('--extra',default='');opt=cli.parse_args()
import bootstrap,unittest,json,sys,importlib.util
from bootstrap import budget,stage
sys.path.insert(0,str(stage/'work/test'))
class CountedResult(unittest.TextTestResult):
 def startTest(self,test):
  self.charge=budget.reserve('case','regression:'+test.id());super().startTest(test)
 def addSubTest(self,test,subtest,err):
  q=budget.reserve('case','regression-sub:'+str(subtest));budget.finish(q,{'passed':err is None});super().addSubTest(test,subtest,err)
 def stopTest(self,test):
  budget.finish(self.charge,{'finished':True});super().stopTest(test)
names=['test_memory_continuity','test_person_memory_identity','test_person_memory_recovery','test_conversation_contract','test_interaction_lifecycle_regression','test_interaction_renewal','test_verified_tool_facts','test_unified_recipient_outbound','test_websocket_session','test_tts_subtitle']
names.extend(n for n in opt.extra.split(',') if n and n not in names)
suite=unittest.TestSuite()
for n in names:
 p=stage/'work/test'/(n+'.py')
 if not p.exists():raise RuntimeError('missing_regression:'+n)
 spec=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(m))
r=unittest.TextTestRunner(verbosity=2,resultclass=CountedResult).run(suite)
(stage/(opt.name+'-summary.json')).write_text(json.dumps({'tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'budget':budget.report()},indent=2))
sys.exit(not r.wasSuccessful())
