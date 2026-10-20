"""Read deployment metadata; never emit environment variables or credentials."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
STAGE=Path(__file__).parent
apps=json.loads(subprocess.check_output(['pm2','jlist'],text=True))
processes=[]
for item in apps:
    env=item.get('pm2_env',{})
    if item.get('name') in {'xiaozhi-server','natural-dialogue-canary'} or 'harness' in item.get('name',''):
        processes.append({k:v for k,v in {'name':item.get('name'),'pid':item.get('pid'),'status':env.get('status'),'script':env.get('pm_exec_path'),'cwd':env.get('pm_cwd'),'interpreter':env.get('exec_interpreter'),'restarts':env.get('restart_time')}.items()})
nginx=subprocess.run(['nginx','-T'],capture_output=True,text=True)
lines=nginx.stdout.splitlines();selected=[]
for i,line in enumerate(lines):
    if any(s in line for s in ['realecho.cn','8000','8003','8006','8010','xiaozhi_ws','Device-Id']):
        selected.append({'line':i+1,'text':line.strip()})
manifest=json.loads((STAGE/'candidate-manifest.json').read_text())
old=json.loads((STAGE/'baseline.json').read_text())
drift={}
for name in manifest:
    path=ROOT/name
    current=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    drift[name]={'exists':path.exists(),'matches_backup':current==old.get(name),'current_hash':current}
listeners=subprocess.run(['ss','-ltnp'],capture_output=True,text=True).stdout
ports=[l for l in listeners.splitlines() if any(':'+str(p)+' ' in l for p in [8000,8003,8006,8010,8013,8016,8020,8023,8026])]
report={'processes':processes,'nginx_syntax_ok':nginx.returncode==0,'nginx_relevant':selected,'source_checks':drift,'listeners':ports}
(STAGE/'deployment-inspection.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,ensure_ascii=False))
