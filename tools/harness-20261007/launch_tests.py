"""Detached evidence workers; never deploy or modify production."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('frozen');p.add_argument('--worker',choices=['single','auxiliary']);a=p.parse_args()
base=Path(__file__).parent;frozen=(base/a.frozen).resolve();assert frozen.is_relative_to(base.resolve()) and frozen.name.startswith('frozen-')
if not a.worker:
    existing=frozen/'jobs.json'
    if existing.exists():raise RuntimeError('Jobs already launched; preserve evidence')
    jobs=[]
    for name in ['single','auxiliary']:
        path=frozen/(name+'-progress.log')
        with path.open('ab') as log:
            child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),a.frozen,'--worker',name],cwd=frozen,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
        jobs.append({'name':name,'pid':child.pid})
    existing.write_text(json.dumps({'started_at':time.time(),'jobs':jobs},indent=2));print(json.dumps(jobs))
else:
    commands=[['run_compare.py','--suite','single','--chain','both','--repeats','3','--concurrency','8','--output','single.jsonl']] if a.worker=='single' else [
      ['run_compare.py','--suite','complex','--chain','both','--repeats','3','--concurrency','3','--output','complex.jsonl'],
      ['run_compare.py','--suite','holdout','--chain','both','--repeats','3','--concurrency','3','--output','holdout.jsonl'],
      ['test_unit.py'],['test_protocol.py'],['test_server_protocol.py'],['run_regressions.py'],['test_full_message_path.py']]
    results=[]
    for command in commands:
        began=time.time();print(json.dumps({'started':command}),flush=True)
        r=subprocess.run([sys.executable,str(frozen/command[0]),*command[1:]],cwd=frozen)
        results.append({'command':command,'exit_code':r.returncode,'elapsed_seconds':round(time.time()-began,3)})
        (frozen/(a.worker+'-jobs-results.json')).write_text(json.dumps(results,indent=2))
        if r.returncode:print(json.dumps({'failed_command':command,'exit_code':r.returncode}),flush=True)
    print(json.dumps({'worker_finished':a.worker,'commands':len(results)}),flush=True)