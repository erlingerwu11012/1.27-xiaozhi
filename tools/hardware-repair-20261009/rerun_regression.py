import bootstrap,sys,json,unittest,contextlib,io
from bootstrap import stage,work,budget
p=work/'test/test_primary_answer_direct_tts.py';s=p.read_text().replace('h.actor = SimpleNamespace(eligible=False,','h.actor = SimpleNamespace(key="synthetic-actor", eligible=False,');p.write_text(s)
sys.path.insert(0,str(work/'test'))
prior=json.loads((stage/'regression-summary.json').read_text())
names=set()
import re
for label,_ in prior['failures']+prior['errors']:
 m=re.match(r'(\w+) \(([^)]+)\)',label)
 if m:names.add(m[2]+'.'+m[1])
class Result(unittest.TextTestResult):
 def startTest(self,t):budget.reserve('case','rerun:'+t.id());super().startTest(t)
log=io.StringIO()
with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):r=unittest.TextTestRunner(stream=log,resultclass=Result,verbosity=2).run(unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in sorted(names)))
(stage/'regression-rerun.log').write_text(log.getvalue());out={'tests':r.testsRun,'failures':[(str(t),s[-2000:]) for t,s in r.failures],'errors':[(str(t),s[-2000:]) for t,s in r.errors],'budget':budget.report()};(stage/'regression-rerun.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False))
