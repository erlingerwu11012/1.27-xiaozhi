"""Publish only the reviewed Python experience changes; automatic rollback."""
from pathlib import Path
import asyncio,hashlib,json,os,shutil,socket,sqlite3,subprocess,time
import pymysql,requests,websockets,yaml

STAGE=Path('/root/prjs/tmp/dialogue-fix-20261017')
ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
OLD=Path('/root/prjs/releases/experience-20261017')
RELEASE=Path('/root/prjs/releases/dialogue-fix-20261017')
PRIVATE=STAGE/'deployment-private'
STATE=STAGE/'deployment.json'
PY='/root/miniconda3/envs/xiaozhi-esp32-server/bin/python'
FILES=['core/handle/sendAudioHandle.py','core/utils/tool_harness/runtime.py','core/utils/tool_harness/retrieval.py','core/utils/tool_harness/request_authority.py','core/utils/tool_harness/prompt_policy.py']

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def apps():return json.loads(subprocess.check_output(['pm2','jlist']))
def command(argv,env=None):
    p=subprocess.run(argv,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    if p.returncode:raise RuntimeError('command_failed:'+argv[0])
def save():STATE.write_text(json.dumps(state,indent=2))
def binding():
    with pymysql.connect(host='127.0.0.1',user='root',password=password,database='xiaozhi_esp32_server',cursorclass=pymysql.cursors.DictCursor) as db:
        with db.cursor() as c:
            c.execute('SELECT id,user_id,agent_id FROM ai_device WHERE mac_address=%s',('ac:a7:04:fd:20:5c',))
            rows=c.fetchall();assert len(rows)==1
            return rows[0]
def api_ready():
    try:
        r=requests.post('http://127.0.0.1:18005/xiaozhi/config/server-base',headers={'Authorization':'Bearer '+secret},json={},timeout=4)
        return r.status_code==200 and r.json().get('data',{}).get('wakeup_words')==['你好小念']
    except (requests.RequestException,ValueError):return False
def ports_ready():
    try:
        for p in [8270,8273,8276]:
            with socket.create_connection(('127.0.0.1',p),timeout=.5):pass
        return True
    except OSError:return False
def wait_ready():
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        if ports_ready():return
        time.sleep(1)
    raise RuntimeError('readiness_timeout')

assert not STATE.exists() and not RELEASE.exists() and not PRIVATE.exists()
verification=json.loads((STAGE/'verification.json').read_text())
assert verification['tests']>=115 and not any(verification[k] for k in ['errors','failures','skipped'])
approval=json.loads((STAGE/'acceptance.json').read_text())
assert approval['accepted'] and approval['physical_tool_calls']==0
assert approval['sha256']=={p:digest(STAGE/'candidate'/p) for p in FILES}
before=apps();old=next(x for x in before if x['pm_id']==18);api=next(x for x in before if x['pm_id']==16)
assert old['pm2_env']['status']=='online' and api['pm2_env']['status']=='online'
assert old['pm2_env']['pm_exec_path']==str(OLD/'serve.py')
assert api['pm2_env']['pm_exec_path']=='/root/prjs/releases/harness-repair-20261017-r2/start-manager-api.sh'
assert all(digest(p)==digest(STAGE/'baseline'/p.relative_to(OLD/'runtime')) for p in (OLD/'runtime').rglob('*.py'))
assert shutil.disk_usage('/').free>1024**3
secret=yaml.safe_load((ROOT/'data/.config.yaml').read_text())['manager-api']['secret']
password=json.loads(Path('/root/prjs/tmp/hardware-followup-20261013/private-test-env.json').read_text())['PERSON_MEMORY_TEST_PASSWORD']
assert api_ready() and ports_ready()
original_binding=binding();config_sha=digest(ROOT/'data/.config.yaml')
env={k.decode():v.decode() for item in (Path('/proc')/str(old['pid'])/'environ').read_bytes().split(b'\0') if b'=' in item for k,v in [item.split(b'=',1)]}
PRIVATE.mkdir(mode=0o700)
error_offset=Path(old['pm2_env']['pm_err_log_path']).stat().st_size
for name,value in [('pm2-before.json',before),('binding-before.json',original_binding)]:
    path=PRIVATE/name;path.write_text(json.dumps(value));path.chmod(0o600)
for source in [ROOT/'data/.config.yaml',ROOT/'config.yaml',OLD/'serve.py']:
    target=PRIVATE/(source.parent.name+'-'+source.name);shutil.copy2(source,target);target.chmod(0o600)
for source in (ROOT/'data').rglob('*.sqlite3'):
    target=PRIVATE/('sqlite-'+str(source.relative_to(ROOT/'data')).replace('/','-'))
    with sqlite3.connect(source) as src,sqlite3.connect(target) as dest:
        src.backup(dest);assert dest.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    target.chmod(0o600)
RELEASE.mkdir();shutil.copytree(OLD/'runtime',RELEASE/'runtime')
for relative in FILES:
    target=RELEASE/'runtime'/relative;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(STAGE/'candidate'/relative,target)
    assert digest(target)==approval['sha256'][relative]
serve=(OLD/'serve.py').read_text().replace(str(OLD/'runtime'),str(RELEASE/'runtime'))
assert str(OLD/'runtime') not in serve
(RELEASE/'serve.py').write_text(serve)
command([PY,'-m','compileall','-q',str(RELEASE/'runtime')])
state={'phase':'prepared','started_at':time.time(),'release':str(RELEASE),'old_python_id':18,'api_id':16,'new_python_id':None,'hardware_tested':False,'error_log_offset':error_offset}
save();switched=False
try:
    state['phase']='switching';save();switched=True
    command(['pm2','stop','18'])
    command(['pm2','start',str(RELEASE/'serve.py'),'--name','xiaozhi-server','--interpreter',PY,'--cwd',old['pm2_env']['pm_cwd']],env=env)
    new=next(x for x in apps() if x['pm2_env'].get('pm_exec_path')==str(RELEASE/'serve.py'))
    state['new_python_id']=new['pm_id'];save();wait_ready()
    assert api_ready()
    assert requests.get('https://www.realecho.cn/',timeout=15).status_code==200
    r=requests.post('https://api.realecho.cn/xiaozhi/config/server-base',headers={'Authorization':'Bearer '+secret},json={},timeout=15)
    assert r.status_code==200 and r.json().get('data',{}).get('wakeup_words')==['你好小念']
    async def negative_wss_probe():
        async with websockets.connect('wss://api.realecho.cn/xiaozhi/v1/',additional_headers={'device-id':'aa:00:00:17:10:fe','client-id':'experience-release-negative-probe','Authorization':'Bearer invalid'},open_timeout=15) as ws:
            try:
                while True:await asyncio.wait_for(ws.recv(),12)
            except websockets.exceptions.ConnectionClosed:
                assert ws.close_code==1008
    asyncio.run(negative_wss_probe())
    assert binding()==original_binding and digest(ROOT/'data/.config.yaml')==config_sha
    active={x['pm_id']:x for x in apps()}
    assert active[new['pm_id']]['pm2_env']['status']=='online'
    assert all(active[x['pm_id']]['pm2_env']['status']==x['pm2_env']['status'] for x in before if x['pm_id']!=18)
    command(['pm2','save'])
    state.update(phase='complete',completed_at=time.time(),checks=['public_https_200','public_api_ready','public_wss_invalid_token_1008','ports_ready','binding_unchanged','config_unchanged','api_and_other_processes_unchanged'],sha256=approval['sha256'])
    save();print(json.dumps(state),flush=True)
except BaseException as e:
    state.update(phase='rolling_back',failure_type=type(e).__name__);save()
    if switched:
        for app in apps():
            if app['pm2_env'].get('pm_exec_path')==str(RELEASE/'serve.py'):command(['pm2','stop',str(app['pm_id'])])
        command(['pm2','restart','18']);wait_ready();command(['pm2','save'])
    state.update(phase='rolled_back',finished_at=time.time());save();raise
