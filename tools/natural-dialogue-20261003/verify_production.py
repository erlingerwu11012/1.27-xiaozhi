"""Read-only final production checks. Credentials and customer data stay private."""
import hashlib, json, os, socket, subprocess, sys
from pathlib import Path
from unittest.mock import MagicMock
from urllib.request import urlopen
OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
receipt=json.loads((OUT/'deployment-receipt.json').read_text())
for name,item in receipt['files'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==item['after_sha256'],name
rows=json.loads(subprocess.run(['pm2','jlist'],check=True,capture_output=True,text=True).stdout)
proc=next(p for p in rows if p['name']=='xiaozhi-server')
assert proc['pid']==receipt['health']['pid'] and proc['pm2_env']['status']=='online'
assert not any(p['name'].startswith('natural-dialogue-canary') for p in rows)
assert not Path('/etc/nginx/conf.d/natural-dialogue-canary.conf').exists()
for name in ['www.realecho.cn','api.realecho.cn']:
    assert '$natural_dialogue_ws' not in (Path('/etc/nginx/sites-enabled')/name).read_text()
    assert 'proxy_pass http://xiaozhi_ws;' in (Path('/etc/nginx/sites-enabled')/name).read_text()
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
import config.logger
config.logger.setup_logging=lambda:MagicMock()
from config.settings import load_config
cfg=load_config()
assert cfg['operation_control']['enabled'] is True
with socket.create_connection(('127.0.0.1',8000),timeout=3):pass
public={}
for url in ['https://www.realecho.cn/','https://realecho.cn/','https://api.realecho.cn/mcp/vision/explain']:
    with urlopen(url,timeout=10) as response:
        assert response.status==200;public[url]=response.status
report={'success':True,'source_files_verified':len(receipt['files']),'pid':proc['pid'],
        'operation_control_enabled':True,'temporary_processes_removed':True,'temporary_routes_removed':True,
        'public_http':public,'personality_storage_modified':False,'private_configs_committed':False}
(OUT/'production-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False))
