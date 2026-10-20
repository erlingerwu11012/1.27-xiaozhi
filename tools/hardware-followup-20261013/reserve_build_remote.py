import sys,json
from pathlib import Path
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
from budget import Budget
b=Budget();c=b.reserve('case','firmware-full-build-01');(s/'firmware-build-charge.json').write_text(json.dumps({'id':c}));print('firmware_build_charge',c)
