from pathlib import Path
p=Path(__file__).parent/'test_http_api.py';s=p.read_text(encoding='utf-8-sig').replace('time.sleep(2);subprocess.run([sys.executable,str(S/\'start_api.py\')],check=True,stdout=subprocess.DEVNULL)', '''import socket
for _ in range(60):
 with socket.socket() as sock:
  if sock.connect_ex(('127.0.0.1',18002))!=0:break
 time.sleep(.5)
else:raise RuntimeError('isolated_api_did_not_stop')
subprocess.run([sys.executable,str(S/'start_api.py')],check=True,stdout=subprocess.DEVNULL)''')
s=s.replace("if r.status_code==200:break", "if r.status_code==200 and r.json().get('code')==0:break");p.write_text(s,encoding='utf-8')
