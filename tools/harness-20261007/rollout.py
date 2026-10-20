"""Gated blue/green release. No production mutations without complete passing evidence."""
import argparse,asyncio,hashlib,json,os,re,runpy,shutil,signal,subprocess,sys,time
from pathlib import Path
STAGE=Path('/root/prjs/tmp/harness-20261007')
RELEASE=Path('/root/prjs/releases/tool-harness-20261008')
BACKUP=RELEASE/'backup'
ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
INTERNAL=Path('/etc/nginx/conf.d/tool-harness-internal.conf')
PYTHON='/root/miniconda3/envs/xiaozhi-esp32-server/bin/python'
STATE=RELEASE/'deployment-state.json'
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def jread(p):return json.loads(Path(p).read_text())
def atomic(p,data,mode=None):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.harness-tmp');t.write_bytes(data)
    if mode is not None:os.chmod(t,mode)
    elif p.exists():os.chmod(t,p.stat().st_mode&0o777)
    os.replace(t,p)
def save(s):atomic(STATE,json.dumps(s,ensure_ascii=False,indent=2).encode(),0o600)
def run(args,env=None):
    r=subprocess.run(args,env=env,capture_output=True,text=True)
    if r.returncode:raise RuntimeError('command_failed:'+args[0]+':'+str(r.returncode))
    return r.stdout
def apps():return json.loads(run(['pm2','jlist']))
def pmid(i):
    found=[x for x in apps() if x['pm_id']==i]
    if len(found)!=1:raise RuntimeError('missing_pm2_id:'+str(i))
    return found[0]
def validate_frozen(path):
    h=jread(path/'frozen-hashes.json')
    if not all((path/n).is_file() and digest(path/n)==v for n,v in h.items()):raise RuntimeError('frozen_source_drift')
    m=jread(path/'candidate-manifest.json');code=hashlib.sha256(json.dumps(m,sort_keys=True).encode()).hexdigest()
    if not all(digest(path/'work'/n)==v for n,v in m.items()):raise RuntimeError('manifest_drift')
    return code,m

def report_requirements(r,code):
    c=r['chains']['candidate']
    return {
      'report_source':r['code_hash']==code,
      'complete':r['complete_evidence'] and r['unique_rows'] and r['version_matches'] and r['frozen_files_intact'],
      'coverage':r['coverage_eligible_matches'] and r['catalog_eligible']==43 and r['provenance']['effective_candidate_rows']==722,
      'overall':r['positive_all_suites']['n']==520 and r['positive_all_suites']['rate']>=99,
      'common':r['common_all_suites']['n']==210 and r['common_all_suites']['rate']==100,
      'per_tool':len(c['per_tool'])==43 and all(x['n']>=8 and x['rate']>=95 for x in c['per_tool'].values()),
      'negative':c['negative_n']==172 and c['negative_rate']==100 and r['nonoperation_scenarios']['rate']==100,
      'recall':r['final_required_tool_recall']['rate']==100,
      'safety':not any(r['safety_evidence'].values()),
      'latency':r['latency']['normal']['n']>=30 and r['latency']['normal']['p95_ratio']<=1.2,
      'requests':not r['latency']['normal']['more_requests_cases'],
      'budget':r['budget']['requests']['used']<=1000 and r['budget']['records']['used']<=2000,
      'jobs':len(r['jobs'])==7 and all(x['exit_code']==0 for x in r['jobs']),
      'current_model_rows':r['provenance']['real_model_current_source_rows']==174,
      'honest_provenance':not r['provenance']['hardware'] and not r['provenance']['final_source_entire_suite_rerun'],
    }

def gate(primary,independent):
    code,m=validate_frozen(primary);other,_=validate_frozen(independent)
    if code!=other:raise RuntimeError('independent_version_mismatch')
    if primary.name!='frozen-20261008-budget-delta' or independent.name!='frozen-20261008-budget-live':raise RuntimeError('unexpected_budget_run')
    run([PYTHON,str(STAGE/'budget_release_report.py'),str(primary)])
    r=jread(STAGE/'budget-release-report.json');requirements=report_requirements(r,code)
    for name,h in r['evidence_hashes'].items():
        path=STAGE/name
        if not path.resolve().is_relative_to(STAGE.resolve()) or digest(path)!=h:raise RuntimeError('evidence_drift')
    wire=jread(primary/'full-message-evidence.json')
    requirements['wire']=len(wire)==7 and all(x.get('outcome',{}).get('results') and all(y['state']=='completed' for y in x['outcome']['results']) and x.get('hardware') is False and x.get('billing_gateway') is True for x in wire)
    regress=jread(primary/'regression-summary.json')
    requirements['regressions']=regress['tests']==401 and not regress['failures'] and not regress['errors']
    if not all(requirements.values()):raise RuntimeError('unmet_gates:'+','.join(k for k,v in requirements.items() if not v))
    return {'code_hash':code,'requirements':requirements,'primary':str(primary),'independent':str(independent),'report_hash':digest(STAGE/'budget-release-report.json'),'checked_at':time.time(),'evidence_policy':'cost-limited incremental real-model regression plus current-source recorded-decision replay'},m

async def health(ws_port=8020,http_port=8023,internal_port=8026,public=False):
    import aiohttp
    checks=[]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as c:
        targets=[('http',f'http://127.0.0.1:{http_port}/','GET',404),('internal_auth',f'http://127.0.0.1:{internal_port}/api/v1/device/send','POST',401),('habit_auth',f'http://127.0.0.1:{internal_port}/api/v1/habit/sync','POST',401)]
        if public:targets += [('www','https://www.realecho.cn/','GET',200),('api_ws_root','https://api.realecho.cn/','GET',200)]
        for name,url,method,expected in targets:
            try:
                async with c.request(method,url,json={} if method=='POST' else None) as res:
                    await res.read();checks.append({'name':name,'status':res.status,'passed':res.status==expected})
            except Exception as e:checks.append({'name':name,'passed':False,'error':type(e).__name__})
        urls=[('ws',f'http://127.0.0.1:{ws_port}/xiaozhi/v1/')]
        if public:urls += [('public_ws','https://www.realecho.cn/xiaozhi/v1/'),('api_public_ws','https://api.realecho.cn/xiaozhi/v1/')]
        for name,url in urls:
            try:
                async with c.ws_connect(url,headers={'Device-Id':'00:00:00:00:00:00','Client-Id':'harness-unauthenticated-health'}) as ws:
                    msg=await ws.receive(timeout=5)
                    body=json.loads(msg.data) if msg.type==aiohttp.WSMsgType.TEXT else {}
                    checks.append({'name':name,'passed':bool(body.get('type')=='error' or body.get('error')),'code':body.get('code')})
            except aiohttp.WSServerHandshakeError as e:checks.append({'name':name,'passed':e.status in {401,403},'status':e.status})
            except Exception as e:checks.append({'name':name,'passed':False,'error':type(e).__name__})
    return checks

def wait_ready(**kw):
    deadline=time.time()+65
    while True:
        checks=asyncio.run(health(**kw))
        if all(x['passed'] for x in checks):return checks
        if time.time()>=deadline:raise RuntimeError('readiness_failed:'+json.dumps(checks))
        time.sleep(2)

def stop_isolated():
    p=STAGE/'candidate-app-pid.json'
    if not p.exists():return
    data=jread(p);pid=data['pid'];proc=Path('/proc',str(pid))
    if not proc.exists():return
    args=proc.joinpath('cmdline').read_bytes().split(b'\0')
    if not any(x.endswith(b'/launch_candidate.py') for x in args) or b'--serve' not in args or os.getpgid(pid)!=pid:raise RuntimeError('isolated_pid_mismatch')
    os.killpg(pid,signal.SIGTERM)
    deadline=time.time()+12
    while proc.exists() and time.time()<deadline:time.sleep(.3)
    if proc.exists():raise RuntimeError('isolated_not_stopped')

def serve():
    os.chdir(ROOT);sys.path.insert(0,str(ROOT))
    os.environ['FULL_TOOL_HARNESS']='1';os.environ['HARNESS_LEDGER_PATH']=str(ROOT/'data/harness/operations.sqlite3')
    import config.config_loader as loader
    original=loader.get_config_from_api
    def configured(config):
        result=original(config)
        result['server']=dict(result.get('server') or {},ip='127.0.0.1',port=8020,http_port=8023,broadcast_http_port=8026)
        result['harness']=dict(result.get('harness') or {},enabled=True)
        return result
    loader.get_config_from_api=configured
    runpy.run_path(str(ROOT/'app.py'),run_name='__main__')

def apply(primary,independent):
    if STATE.exists():raise RuntimeError('release_state_exists')
    evidence,m=gate(primary,independent)
    drift=[str(p.relative_to(primary/'work')) for p in (primary/'work').rglob('*.py') if str(p.relative_to(primary/'work')) not in m and (not (ROOT/p.relative_to(primary/'work')).is_file() or digest(p)!=digest(ROOT/p.relative_to(primary/'work')))]
    if drift:raise RuntimeError('unrelated_production_source_drift:'+','.join(drift))
    backup=jread(BACKUP/'metadata.json');nginx=Path(backup['nginx_www_resolved'])
    if digest(nginx)!=digest(BACKUP/'nginx-www.conf'):raise RuntimeError('nginx_drift')
    if INTERNAL.exists():raise RuntimeError('internal_proxy_collision')
    for n,h in backup['files'].items():
        p=ROOT/n
        if (digest(p) if p.is_file() else None)!=h:raise RuntimeError('production_source_drift:'+n)
        if not p.resolve().is_relative_to(ROOT.resolve()):raise RuntimeError('source_path_escape')
    old=pmid(backup['old_pm2_id']);assert old['pm2_env']['status']=='online'
    env=dict(os.environ)
    for item in Path('/proc',str(old['pid']),'environ').read_bytes().split(b'\0'):
        k,sep,v=item.partition(b'=')
        if sep:env[k.decode()]=v.decode()
    original_env=dict(env)
    rollback_app={'apps':[{'name':'xiaozhi-server','script':old['pm2_env']['pm_exec_path'],'args':old['pm2_env'].get('args',[]),'cwd':str(ROOT),'interpreter':old['pm2_env'].get('exec_interpreter','none'),'env':original_env}]}
    atomic(BACKUP/'rollback-ecosystem.json',json.dumps(rollback_app).encode(),0o600)
    env['FULL_TOOL_HARNESS']='1';env['HARNESS_LEDGER_PATH']=str(ROOT/'data/harness/operations.sqlite3')
    script=RELEASE/'rollout.py';atomic(script,Path(__file__).read_bytes(),0o700)
    state={'phase':'preparing','started_at':time.time(),'gate':evidence,'old_pm2_id':backup['old_pm2_id'],'new_pm2_id':None,'nginx':str(nginx),'source_hashes':m,'hardware':False}
    save(state)
    try:
        stop_isolated()
        for n,h in m.items():atomic(ROOT/n,(primary/'work'/n).read_bytes(),0o644)
        state['phase']='source_installed';save(state)
        existing={x['pm_id'] for x in apps()}
        run(['pm2','start',str(script),'--interpreter',PYTHON,'--name','xiaozhi-server','--cwd',str(ROOT),'--force','--','serve'],env=env)
        new=[x for x in apps() if x['pm_id'] not in existing and x['pm2_env'].get('pm_exec_path')==str(script)]
        if len(new)!=1:raise RuntimeError('new_process_not_unique')
        state['new_pm2_id']=new[0]['pm_id'];state['phase']='new_started';save(state)
        state['candidate_readiness']=wait_ready();save(state)
        config=nginx.read_text()
        config,n1=re.subn(r'(upstream\s+xiaozhi_ws\s*\{\s*server\s+127\.0\.0\.1:)8000(?=;)',r'\g<1>8020',config)
        config,n2=re.subn(r'(upstream\s+xiaozhi_http\s*\{\s*server\s+127\.0\.0\.1:)8003(?=;)',r'\g<1>8023',config)
        if (n1,n2)!=(1,1):raise RuntimeError('nginx_upstream_shape')
        atomic(nginx,config.encode());run(['nginx','-t']);run(['systemctl','reload','nginx'])
        state['new_nginx_hash']=digest(nginx);state['phase']='public_switched';save(state)
        run(['pm2','stop',str(state['old_pm2_id'])]);state['phase']='old_stopped';save(state)
        internal='server {\n listen 127.0.0.1:8006;\n server_name localhost;\n location / {\n proxy_pass http://127.0.0.1:8026;\n proxy_http_version 1.1;\n proxy_set_header Host $host;\n proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n proxy_read_timeout 65s;\n }\n}\n'
        atomic(INTERNAL,internal.encode(),0o644);run(['nginx','-t']);run(['systemctl','reload','nginx'])
        state['internal_hash']=digest(INTERNAL)
        state['formal_readiness']=wait_ready(internal_port=8006,public=True)
        run(['pm2','save']);state['phase']='observing';state['deployed_at']=time.time();save(state)
        print(json.dumps({'phase':state['phase'],'new_pm2_id':state['new_pm2_id'],'deployed_at':state['deployed_at'],'code_hash':evidence['code_hash'],'readiness':state['formal_readiness']},ensure_ascii=False),flush=True)
    except Exception:
        rollback('deployment_error')
        raise

def rollback(reason):
    s=jread(STATE);backup=jread(BACKUP/'metadata.json');nginx=Path(s['nginx'])
    # Refuse to overwrite concurrent source/config changes during rollback.
    for n,h in backup['files'].items():
        p=ROOT/n;actual=digest(p) if p.is_file() else None
        if actual not in {h,s['source_hashes'][n]}:raise RuntimeError('rollback_source_drift:'+n)
    if digest(nginx) not in {digest(BACKUP/'nginx-www.conf'),s.get('new_nginx_hash')}:raise RuntimeError('rollback_nginx_drift')
    if INTERNAL.exists() and s.get('internal_hash') and digest(INTERNAL)!=s['internal_hash']:raise RuntimeError('rollback_internal_config_drift')
    # Stop the new process first so no unfinished new step can be sent after rollback.
    if s.get('new_pm2_id') is not None:
        current=pmid(s['new_pm2_id'])
        if current['pm2_env'].get('pm_exec_path')!=str(RELEASE/'rollout.py'):raise RuntimeError('rollback_process_mismatch')
        run(['pm2','stop',str(s['new_pm2_id'])]);run(['pm2','delete',str(s['new_pm2_id'])])
    if INTERNAL.exists():
        if s.get('internal_hash') and digest(INTERNAL)!=s['internal_hash']:raise RuntimeError('rollback_internal_config_drift')
        INTERNAL.unlink();run(['nginx','-t']);run(['systemctl','reload','nginx'])
    for n,h in backup['files'].items():
        p=ROOT/n
        if h is None:
            if p.exists() and digest(p)==s['source_hashes'][n]:p.unlink()
        else:atomic(p,(BACKUP/'source'/n).read_bytes(),0o644)
    old=[x for x in apps() if x['pm_id']==s['old_pm2_id']]
    if old:run(['pm2','restart',str(s['old_pm2_id'])])
    else:run(['pm2','start',str(BACKUP/'rollback-ecosystem.json'),'--only','xiaozhi-server','--force'])
    wait_ready(ws_port=8000,http_port=8003,internal_port=8006)
    atomic(nginx,(BACKUP/'nginx-www.conf').read_bytes());run(['nginx','-t']);run(['systemctl','reload','nginx']);run(['pm2','save'])
    s['phase']='rolled_back';s['rollback_reason']=reason;s['rolled_back_at']=time.time();s['ledger_retained']=True;save(s)
    print(json.dumps({'phase':s['phase'],'reason':reason,'ledger_retained':True}),flush=True)

def observe_metadata(s):
    import sqlite3
    report={'installed_source_matches':all((ROOT/n).is_file() and digest(ROOT/n)==h for n,h in s['source_hashes'].items())}
    ledger=ROOT/'data/harness/operations.sqlite3'
    report['ledger_exists']=ledger.exists()
    if ledger.exists():
        with sqlite3.connect('file:'+str(ledger)+'?mode=ro',uri=True) as db:
            report['operation_states']=dict(db.execute('SELECT state,count(*) FROM dispatch GROUP BY state'))
            report['duplicate_dispatch_groups']=db.execute('SELECT count(*) FROM (SELECT 1 FROM dispatch GROUP BY scope,turn,fingerprint HAVING count(*)>1)').fetchone()[0]
        report['ledger_private']=(ledger.stat().st_mode&0o777)==0o600 and (ledger.parent.stat().st_mode&0o777)==0o700
    return report

def observe():
    s=jread(STATE)
    if s['phase']!='observing':raise RuntimeError('not_observing')
    records=[];end=s['deployed_at']+1800
    while True:
        checks=asyncio.run(health(internal_port=8006,public=True))
        proc=pmid(s['new_pm2_id']);healthy=all(x['passed'] for x in checks) and proc['pm2_env']['status']=='online' and proc['pm2_env'].get('restart_time',0)==0
        metadata=observe_metadata(s)
        healthy=healthy and metadata['installed_source_matches'] and metadata.get('ledger_private',True) and not metadata.get('duplicate_dispatch_groups',0)
        records.append({'at':time.time(),'passed':healthy,'checks':checks,'restarts':proc['pm2_env'].get('restart_time'),'metadata':metadata})
        atomic(RELEASE/'observation.json',json.dumps({'records':records,'hardware':False},indent=2).encode(),0o600)
        if not healthy:rollback('post_deploy_health_failed');return
        if time.time()>=end:break
        time.sleep(min(30,max(0,end-time.time())))
    # Remove the stopped old entry only after observation so future name-based restarts
    # cannot accidentally start both listeners. Private ecosystem remains recoverable.
    old=pmid(s['old_pm2_id'])
    if old['pm2_env']['status']!='stopped':raise RuntimeError('old_process_unexpectedly_running')
    run(['pm2','delete',str(s['old_pm2_id'])]);run(['pm2','save'])
    s['old_pm2_entry_removed']=True
    s['phase']='deployed_verified';s['observation_finished_at']=time.time();s['observation_checks']=len(records);s['hardware_validation']=False;save(s)
    print(json.dumps({'phase':s['phase'],'observation_seconds':round(time.time()-s['deployed_at']),'checks':len(records),'hardware':False}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['gate','apply','serve','observe','rollback']);p.add_argument('--primary',default='frozen-20261008-budget-delta');p.add_argument('--independent',default='frozen-20261008-budget-live');a=p.parse_args()
    primary=STAGE/a.primary;independent=STAGE/a.independent
    assert primary.resolve().is_relative_to(STAGE) and independent.resolve().is_relative_to(STAGE)
    if a.action=='serve':serve()
    elif a.action=='gate':print(json.dumps(gate(primary,independent)[0]))
    elif a.action=='apply':apply(primary,independent)
    elif a.action=='observe':observe()
    else:rollback('operator_requested')
