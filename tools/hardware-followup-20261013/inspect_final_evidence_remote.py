from pathlib import Path
import json,shutil
s=Path('/root/prjs/tmp/hardware-followup-20261013')
print('evidence_files',[p.name for p in s.glob('*.json') if 'private' not in p.name])
for name in ['final09-freeze.json','api-package-evidence-05.json','holdout-exposure.json']:
 data=json.loads((s/name).read_text());print(name,str(data)[:1800])
print('logs',[p.name for p in s.glob('*.log')])
r=json.loads((s/'final09-results.jsonl').read_text().splitlines()[0]);print('decision_sample',str(r['decisions'])[:2200])
print('disk',shutil.disk_usage('/').free)
