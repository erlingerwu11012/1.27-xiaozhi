"""Private runtime preparation; outputs no credentials."""
import json, os, shutil, subprocess
from pathlib import Path
import yaml

PROD=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
ROOT=Path('/root/prjs/tmp/natural-dialogue-20261003/main/xiaozhi-server')
OUT=ROOT.parents[1]
data=ROOT/'data';data.mkdir(exist_ok=True)
for name in ['.config.yaml','.mcp_server_settings.json']:
    shutil.copy2(PROD/'data'/name,data/name);os.chmod(data/name,0o600)
custom=yaml.safe_load((data/'.config.yaml').read_text())
custom.setdefault('server',{}).update({'ip':'127.0.0.1','port':8010,'http_port':8013})
custom['operation_control']={'enabled':True}
(data/'.config.yaml').write_text(yaml.safe_dump(custom,allow_unicode=True))
for name in ['models']:
    if (PROD/name).exists() and not (ROOT/name).exists():os.symlink(PROD/name,ROOT/name)
processes=json.loads(subprocess.run(['pm2','jlist'],capture_output=True,text=True,check=True).stdout)
prod=next(p for p in processes if p['name']=='xiaozhi-server')['pm2_env']
env={k:v for k,v in prod.items() if k.isupper() and isinstance(v,str)}
env.update({k:v for k,v in (prod.get('env') or {}).items() if k.isupper() and isinstance(v,str)})
env['PYTHONUNBUFFERED']='1'
spec={'apps':[{'name':'natural-dialogue-canary','script':str(OUT/'canary.py'),
    'cwd':str(ROOT),'interpreter':'/root/miniconda3/envs/xiaozhi-esp32-server/bin/python',
    'env':env,'autorestart':False,'out_file':str(OUT/'canary-output.log'),'error_file':str(OUT/'canary-error.log')}]}
path=OUT/'private-canary.config.json';path.write_text(json.dumps(spec));os.chmod(path,0o600)
subprocess.run(['pm2','start',str(path)],check=True,capture_output=True,text=True)
print('isolated canary process started; production routing unchanged')
