from pathlib import Path
import json,os,signal,time,subprocess,socket,sys
S=Path(__file__).parent;p=json.loads((S/'candidate-manager-pid.json').read_text())['pid']
if Path('/proc/'+str(p)).exists():
 cmd=Path('/proc/'+str(p)+'/cmdline').read_bytes();assert str(S/'manager-api/target/xiaozhi-esp32-api.jar').encode() in cmd
 os.kill(p,signal.SIGTERM)
for _ in range(100):
 with socket.socket() as sock:
  if sock.connect_ex(('127.0.0.1',18002))!=0:break
 time.sleep(.1)
else:raise RuntimeError('isolated_port_not_closed')
subprocess.run([sys.executable,str(S/'start_api.py')],check=True)
subprocess.run([sys.executable,str(S/'bind_software_device.py')],check=True)
subprocess.run([sys.executable,str(S/'test_http_api.py')],check=True)
