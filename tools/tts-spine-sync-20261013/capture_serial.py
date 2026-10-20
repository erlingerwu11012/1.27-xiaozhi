import argparse
from datetime import datetime
from pathlib import Path
import re
import time
import serial

p=argparse.ArgumentParser();p.add_argument('--port',default='COM9');p.add_argument('--seconds',type=int,default=25)
a=p.parse_args()
out=Path(__file__).parent/'evidence';out.mkdir(exist_ok=True)
path=out/('serial-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.log')
s=serial.Serial(port=None,baudrate=115200,timeout=0.2)
s.dtr=False;s.rts=False;s.port=a.port;s.open()
pattern=re.compile(r'SPINEBOOT|Spine|role=|nvhai|MAC|TTS_LOCAL|TTS_ANIM|TTS_OUTPUT|STATE:|HOMEPERF|error|reset',re.I)
print('Log port opened without reset: '+a.port+'; file='+str(path),flush=True)
try:
    with path.open('wb') as f:
        end=time.monotonic()+a.seconds;pending=b''
        while time.monotonic()<end:
            data=s.read(4096);f.write(data);f.flush();pending+=data
            while b'\n' in pending:
                line,pending=pending.split(b'\n',1)
                text=line.decode('utf-8','replace')
                if pattern.search(text):print(text,flush=True)
finally:s.close()
