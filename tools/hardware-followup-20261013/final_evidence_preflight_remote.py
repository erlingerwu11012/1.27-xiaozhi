from pathlib import Path
import json,tarfile
s=Path('/root/prjs/tmp/hardware-followup-20261013')
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
for name in ['deterministic-05.log','ota-api-03.log','lifecycle-04.log','network-stream-02.log','confirmation-01.log','selection-03.log','ingress-01.log','vision-http-03.log','quality-unit-01.log','weather-unit01.log','internal-id-unit01.log','greeting-unit03.log']:
 print(name,'OK' in (s/name).read_text(),'\n'.join((s/name).read_text().splitlines()[-4:]))
for name in ['firmware-build-charge-02.json','host-charges-02.json','ota-lock-host-charge.json']:
 print(name,(s/name).read_text())
