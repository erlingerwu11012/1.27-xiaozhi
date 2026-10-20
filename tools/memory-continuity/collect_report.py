import json,re,xml.etree.ElementTree as ET
from pathlib import Path
out=Path('/root/prjs/tmp/memory-continuity-release-20260930')
roots=[ET.parse(p).getroot() for p in Path('/root/prjs/tmp/bailian-memory-product/main/manager-api/target/surefire-reports').glob('TEST-*.xml')]
java={key:sum(int(r.get(key,0)) for r in roots) for key in ('tests','failures','errors','skipped')}
python={}
for p in out.glob('voice-*.log'):
 m=re.search(r'Ran (\d+) tests?',p.read_text(errors='replace'));python[p.stem]=int(m.group(1)) if m else 0
real=json.loads((out/'real-tests.json').read_text());published=json.loads((out/'published.json').read_text());post=json.loads((out/'postcheck.json').read_text())
assert java['errors']==java['failures']==java['skipped']==0
result={'java':java,'python_tests':sum(python.values()),'python_suites':len(python),'test_wallet_cny':real['charged_cny'],'upstream_upper_estimate_cny':real['upstream_upper_estimate_cny'],'compression':{k:v for k,v in real['compression'].items() if k!='summary_json'},'long_input':real.get('long_input'),'cloud_test_nodes':2,'test_facts_cleaned':real['test_facts_cleaned'],'local_production_passed':real['local_production_passed'],'local_test_rows_cleaned':real['local_test_rows_cleaned'],'published':published,'postcheck':post,'manual_error_window':json.loads((out/'error-window.json').read_text())}
(out/'safe-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
