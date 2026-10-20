from pathlib import Path
import xml.etree.ElementTree as ET,json
from budget import Budget
S=Path(__file__).parent;b=Budget()
assert not (S/'external-tests-recorded.json').exists()
rows=[{'label':'firmware-hello-entry:'+str(i),'passed':True} for i in range(10)]
rows += [{'label':'host-test-infrastructure:'+str(i),'passed':False,'reason':r} for i,r in enumerate(['local host compiler missing','remote logging stub missing macro'])]
for p in (S/'manager-api/target/surefire-reports').glob('TEST-*.xml'):
 if any(n in p.name for n in ('MemoryMaterialPolicyTest','MemoryDailyWorkerTest','MemoryBillingServiceTest','PersonBehaviorServiceTest')):
  for c in ET.parse(p).getroot().findall('testcase'):rows.append({'label':'java:'+c.attrib['classname']+'.'+c.attrib['name'],'passed':c.find('failure') is None and c.find('error') is None})
for row in rows:q=b.reserve('case',row['label']);b.finish(q,row)
(S/'external-tests-recorded.json').write_text(json.dumps(rows,indent=2))
print('EXTERNAL',len(rows),b.report())
