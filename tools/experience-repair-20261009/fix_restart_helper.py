from pathlib import Path
p=Path(__file__).parent/'restart_test_api.py';s=p.read_text(encoding='utf-8-sig').replace('except ProcessLookupError:pass','''except ProcessLookupError:pass
import time,socket
for _ in range(60):
 with socket.socket() as sock:
  if sock.connect_ex(('127.0.0.1',18002))!=0:break
 time.sleep(.5)
else:raise RuntimeError('isolated_api_did_not_stop')''');p.write_text(s,encoding='utf-8')
