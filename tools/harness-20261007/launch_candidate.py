"""Isolated app readiness, no proxy changes and no production device sessions."""
import argparse,json,os,runpy,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('work');p.add_argument('--serve',action='store_true');a=p.parse_args()
work=Path(a.work).resolve();stage=Path(__file__).parent
assert work.is_relative_to(stage.resolve()) and (work/'app.py').is_file()
if not a.serve:
    env=dict(os.environ)
    pid=subprocess.check_output(['pm2','pid','xiaozhi-server'],text=True).strip().splitlines()[-1]
    for field in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0'):
        key,sep,value=field.partition(b'=')
        if sep:env[key.decode()]=value.decode()
    env['FULL_TOOL_HARNESS']='1';env['HARNESS_LEDGER_PATH']=str(stage/'candidate-ledger/operations.sqlite3')
    logpath=stage/'candidate-app.log'
    with logpath.open('ab') as log:
        os.chmod(logpath,0o600)
        child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),str(work),'--serve'],cwd=work,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    (stage/'candidate-app-pid.json').write_text(json.dumps({'pid':child.pid,'work':str(work),'ports':[8020,8023,8026]}))
    print(json.dumps({'candidate_pid':child.pid,'ports':[8020,8023,8026],'production_untouched':True}))
else:
    os.chdir(work);sys.path.insert(0,str(work))
    import config.config_loader as loader
    original=loader.get_config_from_api
    def isolated(config):
        result=original(config)
        result['server']=dict(result.get('server') or {},ip='127.0.0.1',port=8020,http_port=8023,broadcast_http_port=8026)
        result['harness']={'enabled':True}
        result['log']=dict(result.get('log') or {},log_dir=str(stage/'candidate-logs'))
        result['trace_log']=dict(result.get('trace_log') or {},dir=str(stage/'candidate-trace'))
        return result
    loader.get_config_from_api=isolated
    runpy.run_path(str(work/'app.py'),run_name='__main__')