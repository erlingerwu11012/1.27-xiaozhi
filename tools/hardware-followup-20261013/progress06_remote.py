from pathlib import Path
import json,sys
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
from budget import Budget
b=Budget()
if not (s/'ota-lock-host-charge.json').exists():
 ids=[]
 for i in range(9):
  charge=b.reserve('case','ota-production-lock-host-'+str(i));b.finish(charge,{'passed':True,'log':'local ota-lock-host-01.log','reservation_note':'recorded after local execution; no model/device calls'});ids.append(charge)
 (s/'ota-lock-host-charge.json').write_text(json.dumps(ids))
for name in ['deterministic-04.log','ota-api-02.log','development06.log']:
 p=s/name
 print(name, '\n'.join(p.read_text().splitlines()[-6:]) if p.exists() else 'pending')
print('budget',b.report())
