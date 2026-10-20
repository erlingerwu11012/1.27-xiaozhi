"""Run on the server: publish only the retired-touch cleanup, with rollback."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import socket
import subprocess
import time

STAGE=Path('/root/prjs/tmp/tts-spine-sync-20261013')
OLD=Path('/root/prjs/releases/harness-followup-20261013')
NEW=Path('/root/prjs/releases/tts-spine-sync-20261013')
FILES=['core/connection.py','core/providers/tools/device_mcp/mcp_handler.py']
def apps():return json.loads(subprocess.check_output(['pm2','jlist']))
def run(args,**kwargs):return subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kwargs)
def ready():
    try:
        for port in (8270,8273,8276):
            with socket.create_connection(('127.0.0.1',port),timeout=1):pass
        return True
    except OSError:return False
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    active=[a for a in apps() if a['name']=='xiaozhi-server' and a['pm2_env']['status']=='online']
    assert len(active)==1
    old=active[0];assert old['pm2_env']['pm_exec_path']==str(OLD/'serve.py')
    expected=json.loads((STAGE/'before-hashes.json').read_text())
    for f in FILES:assert sha(OLD/'runtime'/f)==expected[f],f+' changed since baseline'
    assert not NEW.exists(),'Release already exists; inspect before rerunning'
    assert shutil.disk_usage('/').free>100*1024*1024
    NEW.mkdir()
    shutil.copytree(OLD/'runtime',NEW/'runtime',symlinks=True,ignore=shutil.ignore_patterns('__pycache__'))
    wrapper=(OLD/'serve.py').read_text().replace(str(OLD/'runtime'),str(NEW/'runtime'))
    assert str(NEW/'runtime') in wrapper
    (NEW/'serve.py').write_text(wrapper)
    for f in FILES:
        patch=STAGE/'server'/f
        compile(patch.read_text(),str(patch),'exec')
        shutil.copy2(patch,NEW/'runtime'/f)
    # All other Python sources must match the running release exactly.
    for path in (OLD/'runtime').rglob('*.py'):
        rel=str(path.relative_to(OLD/'runtime'))
        if rel not in FILES:assert sha(path)==sha(NEW/'runtime'/rel),rel
    run(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python',str(STAGE/'test_server_touch.py')])
    env={k.decode():v.decode() for item in (Path('/proc')/str(old['pid'])/'environ').read_bytes().split(b'\0')
         if b'=' in item for k,v in [item.split(b'=',1)]}
    state={'old_release':str(OLD),'new_release':str(NEW),'old_pm2_id':old['pm_id'],
           'old_pid':old['pid'],'phase':'prepared','changed_files':FILES,
           'before_hashes':expected,'after_hashes':{f:sha(NEW/'runtime'/f) for f in FILES},
           'database_changed':False,'nginx_changed':False}
    state_path=NEW/'deployment.json'
    def save():state_path.write_text(json.dumps(state,indent=2))
    save();new_id=None
    try:
        run(['pm2','stop',str(old['pm_id'])])
        run(['pm2','start',str(NEW/'serve.py'),'--name','xiaozhi-server','--interpreter',
             old['pm2_env']['exec_interpreter'],'--cwd',old['pm2_env']['pm_cwd']],env=env)
        for _ in range(40):
            new=next((a for a in apps() if a['pm2_env'].get('pm_exec_path')==str(NEW/'serve.py')),None)
            if new:new_id=new['pm_id']
            if new and new['pm2_env']['status']=='online' and ready():break
            time.sleep(1)
        else:raise RuntimeError('New server did not become ready')
        # Check again after the initial import/startup interval.
        time.sleep(3)
        assert ready()
        new=next(a for a in apps() if a['pm_id']==new_id)
        assert new['pm2_env']['status']=='online'
        run(['pm2','save'])
        state.update(phase='deployed',new_pm2_id=new_id,new_pid=new['pid'],deployed_at=time.time(),
                     hardware_accepted=False)
        save();print(json.dumps(state),flush=True)
    except BaseException:
        if new_id is not None:run(['pm2','stop',str(new_id)])
        run(['pm2','restart',str(old['pm_id'])]);run(['pm2','save'])
        state.update(phase='rolled_back');save();raise

if __name__=='__main__':main()
