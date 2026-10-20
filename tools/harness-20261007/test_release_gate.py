import copy,json,unittest
from pathlib import Path
from rollout import report_requirements,STAGE
class ReleaseGate(unittest.TestCase):
 def test_real_report_passes(self):
  r=json.loads((STAGE/'budget-release-report.json').read_text());self.assertTrue(all(report_requirements(r,r['code_hash']).values()))
 def test_reject_modified_results(self):
  r=json.loads((STAGE/'budget-release-report.json').read_text())
  edits=[('common_all_suites','rate',99.9),('positive_all_suites','rate',98.9),('latency','normal',dict(r['latency']['normal'],p95_ratio=1.21)),('safety_evidence','duplicate_write_turns',[{'id':'bad'}]),('provenance','real_model_current_source_rows',173),('budget','records',{'used':2001,'limit':2000})]
  for group,key,value in edits:
   x=copy.deepcopy(r);x[group][key]=value;self.assertFalse(all(report_requirements(x,r['code_hash']).values()),(group,key))
  self.assertFalse(all(report_requirements(r,'wrong-source').values()))
  x=copy.deepcopy(r);x['latency']['normal']['more_requests_cases']=[{'id':'extra'}];self.assertFalse(all(report_requirements(x,r['code_hash']).values()))
if __name__=='__main__':unittest.main()
