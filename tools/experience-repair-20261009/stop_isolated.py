import os,signal,json,subprocess,socket,time
from pathlib import Path
S=Path(__file__).parent;stopped=[]
for p in Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:args=(p/'cmdline').read_bytes().split(b'\0')
 except OSError:continue
 if b'--server.port=18002' in args and str(S/'manager-api/target/xiaozhi-esp32-api.jar').encode() in args:
  os.kill(int(p.name),signal.SIGTERM);stopped.append(int(p.name))
deadline=time.time()+20
while time.time()<deadline:
 with socket.socket() as sock:
  if sock.connect_ex(('127.0.0.1',18002))!=0:break
 time.sleep(.2)
else:raise RuntimeError('isolated_api_not_stopped')
subprocess.run(['docker','stop','experience-repair-redis'],check=True,capture_output=True)
out={'isolated_api_stopped_pids':stopped,'isolated_redis_stopped':True,'test_database_retained':True,'production_modified':False,'at':time.time()};(S/'test-environment-cleanup.json').write_text(json.dumps(out));print(json.dumps(out))
