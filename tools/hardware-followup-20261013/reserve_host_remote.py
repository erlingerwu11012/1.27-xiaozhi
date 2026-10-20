from pathlib import Path
import sys,json
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
from budget import Budget
b=Budget();data={}
for suite,count in [('tts-owner-and-playback',24),('hello-protocol-entry',10),('usb-recovery',7),('face-terminal',5)]:data[suite]=[b.reserve('case','firmware-host-01:'+suite+':'+str(i)) for i in range(count)]
(s/'host-charges-01.json').write_text(json.dumps(data));print('reserved_host_scenarios',sum(map(len,data.values())))
