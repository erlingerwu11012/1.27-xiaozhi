import bootstrap,unittest,json,sys
from bootstrap import budget,stage,work
sys.path.insert(0,str(work/'test'))
class Result(unittest.TextTestResult):
 def startTest(self,t):budget.reserve('case',t.id());super().startTest(t)
names=['test_repair','test_vision_capability','test_vision_identify']
r=unittest.TextTestRunner(verbosity=1,resultclass=Result).run(unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names))
(stage/'latest-regression-summary.json').write_text(json.dumps({'tests':r.testsRun,'failures':[str(t) for t,s in r.failures],'errors':[str(t) for t,s in r.errors],'budget':budget.report()},indent=2));raise SystemExit(not r.wasSuccessful())

