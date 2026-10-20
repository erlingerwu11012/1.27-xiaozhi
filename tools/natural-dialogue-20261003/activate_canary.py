"""Temporarily route only the authorized MAC to the tested candidate."""
import json, os, shutil, socket, subprocess, time
from pathlib import Path
from urllib.request import Request,urlopen
import yaml
OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
PROD=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
DEVICE='ac:a7:04:fd:20:2c'
for attempt in range(20):
    try:
        with socket.create_connection(('127.0.0.1',8010),timeout=2):pass
        break
    except OSError:
        if attempt==19:raise
        time.sleep(1)
paths=[Path('/etc/nginx/sites-enabled/www.realecho.cn').resolve(),Path('/etc/nginx/sites-enabled/api.realecho.cn').resolve()]
new=Path('/etc/nginx/conf.d/natural-dialogue-canary.conf')
assert not new.exists(),'canary configuration already exists'
backup=OUT/'nginx-before-canary';backup.mkdir(exist_ok=False)
manifest={}
for p in paths:
    shutil.copy2(p,backup/p.name)
    assert 'proxy_pass http://xiaozhi_ws;' in p.read_text()
    manifest[str(p)]=__import__('hashlib').sha256(p.read_bytes()).hexdigest()
(backup/'manifest.json').write_text(json.dumps(manifest))
try:
    new.write_text('map $http_device_id $natural_dialogue_ws {\n default xiaozhi_ws;\n "'+DEVICE+'" natural_dialogue_canary;\n}\nupstream natural_dialogue_canary { server 127.0.0.1:8010; }\n')
    for p in paths:p.write_text(p.read_text().replace('proxy_pass http://xiaozhi_ws;','proxy_pass http://$natural_dialogue_ws;'))
    subprocess.run(['nginx','-t'],capture_output=True,text=True,check=True)
    subprocess.run(['nginx','-s','reload'],capture_output=True,text=True,check=True)
except Exception:
    for p in paths:shutil.copy2(backup/p.name,p)
    if new.exists():new.unlink()
    subprocess.run(['nginx','-s','reload'],capture_output=True,text=True)
    raise
# Prompt selected device to open a NEW WebSocket, without revoking credentials.
# Existing server's targeted send preserves device/current-session guards.
config=yaml.safe_load((PROD/'data/.config.yaml').read_text())
secret=config['manager-api']['secret']
payload={'device_id':DEVICE,'payload':{'type':'goodbye'}}
req=Request('http://127.0.0.1:8006/api/v1/device/send',data=json.dumps(payload).encode(),method='POST',headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
with urlopen(req,timeout=5) as response:sent=json.load(response)
print(json.dumps({'route':'selected test MAC only','default':'production unchanged','device_reconnect_message':sent}))
