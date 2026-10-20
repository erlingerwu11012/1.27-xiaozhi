"""Stage an independent release without changing production processes or data."""
from pathlib import Path
import hashlib,json,shutil,os,time
S=Path(__file__).parent
OLD=Path('/root/prjs/releases/mcp-prune-20261010')
NEW=Path('/root/prjs/releases/harness-stream-20261012')
ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
assert not NEW.exists(),'Never overwrite a staged release'
assert shutil.disk_usage('/').free>750*1024**2,'Need space for release and rollback'
preflight=json.loads((S/'release-preflight-v2.json').read_text())
assert not preflight['live_baseline_drift']
freeze=json.loads((S/'final18-frozen.json').read_text())
for name,value in freeze['files'].items():
 if name.startswith('work/') and not name.startswith('work/test/'):
  assert hashlib.sha256((S/name).read_bytes()).hexdigest()==value,('Candidate drift',name)
NEW.mkdir(mode=0o700)
shutil.copytree(OLD/'runtime',NEW/'runtime',symlinks=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
changed=[]
for name in preflight['changed_source']:
 if name.startswith('test/'):continue
 source=S/'work'/name;target=NEW/'runtime'/name
 target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);changed.append(name)
shutil.copy2(S/'work/agent-base-prompt-v2.txt',NEW/'runtime/agent-base-prompt-v2.txt')
shutil.copy2(S/'manager-api/target/xiaozhi-esp32-api.jar',NEW/'xiaozhi-esp32-api.jar')
old_api=Path('/root/prjs/releases/hardware-repair-20261009/start-manager-api.sh')
start=old_api.read_text();needle='/root/prjs/releases/hardware-repair-20261009/xiaozhi-esp32-api.jar'
assert start.count(needle)==1
(NEW/'start-manager-api.sh').write_text(start.replace(needle,str(NEW/'xiaozhi-esp32-api.jar')))
(NEW/'start-manager-api.sh').chmod(0o700)
wrapper='''from pathlib import Path
import os,sys,runpy
ROOT=Path("/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server")
RUNTIME=Path("/root/prjs/releases/harness-stream-20261012/runtime")
candidate=os.environ.get("XIAOZHI_RELEASE_CANDIDATE")=="1"
os.chdir(ROOT);sys.path.insert(0,str(RUNTIME));os.environ["FULL_TOOL_HARNESS"]="1"
os.environ["HARNESS_LEDGER_PATH"]=str(Path("/root/prjs/tmp/harness-stream-20261011/candidate-operations.sqlite3") if candidate else ROOT/"data/harness/operations.sqlite3")
if candidate:os.environ["PERSON_MATERIAL_OUTBOX"]="/root/prjs/tmp/harness-stream-20261011/candidate-material-outbox.sqlite3"
import config.config_loader as loader
original=loader.get_config_from_api
def configure(c):
 r=original(c);r["server"]=dict(r.get("server") or {},ip="127.0.0.1",port=8170 if candidate else 8070,http_port=8173 if candidate else 8073,broadcast_http_port=8176 if candidate else 8076);r["harness"]=dict(r.get("harness") or {},enabled=True);return r
loader.get_config_from_api=configure
import core.utils.prompt_manager as prompt_manager
prompt_manager.V2_PLATFORM_TEMPLATE_PATH=str(RUNTIME/"agent-base-prompt-v2.txt")
runpy.run_path(str(RUNTIME/"app.py"),run_name="__main__")
'''
(NEW/'serve.py').write_text(wrapper)
hashes={str(p.relative_to(NEW)):hashlib.sha256(p.read_bytes()).hexdigest() for p in NEW.rglob('*') if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts and not any(x in p.relative_to(NEW).parts for x in ('logs','tmp','data','models'))}
manifest={'release':str(NEW),'rollback_release':str(OLD),'prepared_at':time.time(),'source_freeze':'final18','changed_sources':changed,'hashes':hashes,'production_processes_changed':False,'production_database_changed':False,'gateway_changed':False,'api_start_only_jar_path_changed':True,'prompt_template_absolute_path':True}
(NEW/'release-manifest.json').write_text(json.dumps(manifest,indent=2));(S/'staged-release-manifest.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps({'release':str(NEW),'changed_sources':len(changed),'free_bytes':shutil.disk_usage('/').free}))
