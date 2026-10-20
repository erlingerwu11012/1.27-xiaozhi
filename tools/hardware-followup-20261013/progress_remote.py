from pathlib import Path
import sys,json
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
from budget import Budget
print(json.dumps(Budget().report()))
p=s/'development02.log';print('\n'.join(p.read_text().splitlines()[-6:]))
