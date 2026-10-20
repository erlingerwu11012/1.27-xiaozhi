"""Remove only this task's exact temporary routing and stop its test process."""
import json, hashlib, shutil, subprocess
from pathlib import Path
OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
saved=OUT/'nginx-before-canary'
manifest=json.loads((saved/'manifest.json').read_text())
paths={}
for name,sha in manifest.items():
    path=Path(name);original=(saved/path.name).read_bytes()
    assert hashlib.sha256(original).hexdigest()==sha
    expected=original.decode().replace('proxy_pass http://xiaozhi_ws;','proxy_pass http://$natural_dialogue_ws;').encode()
    assert path.read_bytes()==expected,'nginx concurrently changed: '+name
    paths[path]=original
extra=Path('/etc/nginx/conf.d/natural-dialogue-canary.conf')
expected_extra='map $http_device_id $natural_dialogue_ws {\n default xiaozhi_ws;\n "ac:a7:04:fd:20:2c" natural_dialogue_canary;\n}\nupstream natural_dialogue_canary { server 127.0.0.1:8010; }\n'
assert extra.read_text() in {expected_extra, expected_extra.replace('8010','8011')}
expected_extra=extra.read_text()
try:
    for path,data in paths.items():path.write_bytes(data)
    extra.unlink()
    subprocess.run(['nginx','-t'],check=True,capture_output=True)
    subprocess.run(['nginx','-s','reload'],check=True,capture_output=True)
except Exception:
    for path,data in paths.items():path.write_bytes(data.decode().replace('proxy_pass http://xiaozhi_ws;','proxy_pass http://$natural_dialogue_ws;').encode())
    extra.write_text(expected_extra)
    subprocess.run(['nginx','-s','reload'],capture_output=True)
    raise
rows=json.loads(subprocess.run(['pm2','jlist'],check=True,capture_output=True,text=True).stdout)
for name in ['natural-dialogue-canary','natural-dialogue-canary-next']:
    if any(p['name']==name for p in rows):
        subprocess.run(['pm2','delete',name],check=True,capture_output=True)
receipt_path=OUT/'deployment-receipt.json'
if receipt_path.exists():
    receipt=json.loads(receipt_path.read_text());receipt['canary_routes_cleanup_pending']=False
    receipt['test_process_removed']=True;receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
print('temporary canary routing removed; all devices now use production')
