"""Private deployment backup only; never change production files or processes."""
import hashlib,json,os,shutil,subprocess,time
from pathlib import Path
stage=Path(__file__).resolve().parent
root=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
release=Path('/root/prjs/releases/tool-harness-20261008')
release.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(release,0o700)
backup=release/'backup'
if backup.exists():raise RuntimeError('Backup exists; preserve it and verify drift separately')
backup.mkdir(mode=0o700)
manifest=json.loads((stage/'candidate-manifest.json').read_text());baseline=json.loads((stage/'baseline.json').read_text())
files={}
for name in manifest:
    f=root/name;actual=hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None
    if actual!=baseline.get(name):raise RuntimeError('Source drift: '+name)
    files[name]=actual
    if f.is_file():
        out=backup/'source'/name;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,out)
apps=json.loads(subprocess.check_output(['pm2','jlist'],text=True))
old=[p for p in apps if p.get('name')=='xiaozhi-server' and p['pm2_env'].get('status')=='online']
if len(old)!=1:raise RuntimeError('Expected exactly one current production service')
proc=old[0];pid=proc['pid']
for name,data in [('pm2-private.json',json.dumps(proc,ensure_ascii=False,indent=2).encode()),('process-env.bin',Path('/proc',str(pid),'environ').read_bytes())]:
    f=backup/name;f.write_bytes(data);os.chmod(f,0o600)
for config in (root/'data').glob('*.yaml'):
    out=backup/'private-config'/config.name;out.parent.mkdir(parents=True,exist_ok=True,mode=0o700);shutil.copy2(config,out);os.chmod(out,0o600)
for config in [root/'.config.yaml',root/'.mcp_server_settings.json']:
    if config.is_file():
        out=backup/'private-config'/config.name;out.parent.mkdir(parents=True,exist_ok=True,mode=0o700);shutil.copy2(config,out);os.chmod(out,0o600)
nginx=Path('/etc/nginx/sites-enabled/www.realecho.cn').resolve()
shutil.copy2(nginx,backup/'nginx-www.conf')
info={'created_at':time.time(),'root':str(root),'files':files,'old_pm2_id':proc['pm_id'],'old_pid':pid,'nginx_www_resolved':str(nginx),'production_modified':False}
(backup/'metadata.json').write_text(json.dumps(info,indent=2));print(json.dumps({'backup':str(backup),'source_files':len(files),'old_pm2_id':proc['pm_id'],'production_modified':False}))
