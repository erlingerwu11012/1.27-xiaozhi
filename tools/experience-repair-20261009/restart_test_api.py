import os,json,signal,subprocess,sys
from pathlib import Path
S=Path(__file__).parent;p=json.loads((S/'candidate-manager-pid.json').read_text())
try:os.kill(p['pid'],signal.SIGTERM)
except ProcessLookupError:pass
import time,socket
for _ in range(60):
 with socket.socket() as sock:
  if sock.connect_ex(('127.0.0.1',18002))!=0:break
 time.sleep(.5)
else:raise RuntimeError('isolated_api_did_not_stop')
subprocess.run([sys.executable,str(S/'start_api.py')],check=True)
