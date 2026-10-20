"""Source-only production promotion with exact baseline checks and rollback."""
import hashlib, json, os, shutil, socket, subprocess, time
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import urlopen

REPO=Path('/root/prjs/xiaozhi-esp32-server')
ROOT=REPO/'main/xiaozhi-server'
OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
CANDIDATE=OUT/'main/xiaozhi-server'
BASELINE='79e4ed56a6ddd418452bdcd88fecb7d0b296c544'
def command(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=45).stdout
def digest(data):return hashlib.sha256(data).hexdigest()
def read(name):return json.loads((OUT/name).read_text())

assert command('git','-C',str(REPO),'rev-parse','HEAD').strip()==BASELINE,'production HEAD changed'
assert not command('git','-C',str(REPO),'status','--porcelain','--untracked-files=no').strip(),'production tracked files changed'
regression=read('regression.json')
model=read('model-acceptance.json')
repeats=read('model-failure-revalidation.json')
style=read('style-revalidation.json')
hardware=read('hardware-acceptance.json')
live=read('live-chain-acceptance.json')
pipeline=read('pipeline-acceptance.json')
latency=read('latency-acceptance.json')
assert regression['success'] and regression['run']>=194
assert model['summary']['cases']>=100 and model['summary']['runtime_pass']==model['summary']['cases']
assert repeats['success'] and repeats['summary']['runtime_pass']==repeats['summary']['cases']
assert len(style['cases'])>=66 and all('error_type' not in c and c['persona_preserved'] for c in style['cases'])
assert not any(c['flags'] for c in style['cases'] if c['persona']==style['cases'][0]['persona'])
assert hardware['success'] and hardware['persona_unchanged'] and all(hardware['restoration'].values())
assert hardware['temporary_record']['cleaned']
assert live['summary']['mcp_pass']==3 and live['summary']['voice_contract_matches']==20
assert pipeline['success'] and pipeline['source_sha256']==digest((CANDIDATE/'core/utils/operation_control.py').read_bytes())
assert latency['summary']['provisional_latency_gate_pass']

names=(OUT/'changed-files.txt').read_text().splitlines()
assert len(names)==18 and len(set(names))==18
prepared={};manifest={}
for name in names:
    assert '..' not in Path(name).parts and not Path(name).is_absolute()
    path=ROOT/name;data=(CANDIDATE/name).read_bytes()
    if name.endswith('.py'):compile(data.decode('utf-8'),name,'exec')
    existed=path.exists()
    if existed:
        baseline=subprocess.run(['git','-C',str(REPO),'show',BASELINE+':main/xiaozhi-server/'+name],check=True,capture_output=True).stdout
        assert path.read_bytes()==baseline,'baseline source differs: '+name
    prepared[name]=data
    manifest[name]={'before_sha256':digest(path.read_bytes()) if existed else None,'after_sha256':digest(data)}
procs=json.loads(command('pm2','jlist'))
proc=next(p for p in procs if p['name']=='xiaozhi-server')
assert proc['pm2_env']['pm_cwd']==str(ROOT)
stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-utc')
backup=OUT/('production-backup-'+stamp);backup.mkdir()
for name in names:
    path=ROOT/name
    if path.exists():
        dst=backup/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dst)
(backup/'manifest.json').write_text(json.dumps(manifest,indent=2))

def health():
    proc=next(p for p in json.loads(command('pm2','jlist')) if p['name']=='xiaozhi-server')
    assert proc['pm2_env']['status']=='online'
    with socket.create_connection(('127.0.0.1',8000),timeout=3):pass
    with urlopen('http://127.0.0.1:8003/mcp/vision/explain',timeout=5) as response:assert response.status==200
    return {'pid':proc['pid'],'status':'online','ws_port':8000,'vision_http_status':200}

changed=[]
try:
    for name,data in prepared.items():
        path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_name(path.name+'.natural-dialogue-new');temp.write_bytes(data)
        if path.exists():shutil.copystat(path,temp)
        os.utime(temp,None);os.replace(temp,path);changed.append(name)
    command('pm2','restart','xiaozhi-server')
    first=None
    for _ in range(15):
        time.sleep(2)
        try:first=health();break
        except Exception:pass
    assert first,'production health failed'
    time.sleep(4);stable=health();assert stable['pid']==first['pid'],'production restart loop'
    public={}
    for url in ['https://www.realecho.cn/','https://realecho.cn/','https://api.realecho.cn/mcp/vision/explain']:
        with urlopen(url,timeout=12) as response:
            assert response.status==200;public[url]=response.status
except Exception:
    for name in changed:
        path=ROOT/name;saved=backup/name
        if saved.exists():shutil.copy2(saved,path);os.utime(path,None)
        else:path.unlink()
    command('pm2','restart','xiaozhi-server')
    (OUT/'deployment-failure.json').write_text(json.dumps({'rolled_back':True,'backup':str(backup)}))
    raise

receipt={'deployed_at_utc':datetime.now(timezone.utc).isoformat(),'baseline_commit':BASELINE,
         'backup':str(backup),'files':manifest,'health':stable,'public_http':public,
         'personality_changed':False,'secondary_rewrite_model':False,'new_version_ui':False,
         'operation_control_enabled':True,'canary_routes_cleanup_pending':True}
(OUT/'deployment-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
print(json.dumps({'deployed':True,'files':len(manifest),'health':stable,'public_http':public,'backup':str(backup)}))
