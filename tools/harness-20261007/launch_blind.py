import argparse,json,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('frozen');p.add_argument('--worker',action='store_true');a=p.parse_args()
stage=Path(__file__).parent;frozen=(stage/a.frozen).resolve();assert frozen.is_relative_to(stage.resolve()) and frozen.name.startswith('frozen-')
if not a.worker:
    assert not (frozen/'blind-job.json').exists()
    with (frozen/'blind-progress.log').open('ab') as log:
        child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),a.frozen,'--worker'],cwd=frozen,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
    (frozen/'blind-job.json').write_text(json.dumps({'pid':child.pid,'started_at':time.time()},indent=2));print(json.dumps({'blind_worker':child.pid}))
else:
    began=time.time();command=[sys.executable,str(frozen/'run_compare.py'),'--suite','holdout','--chain','both','--repeats','3','--concurrency','2','--output','holdout.jsonl']
    r=subprocess.run(command,cwd=frozen)
    (frozen/'blind-job-result.json').write_text(json.dumps({'exit_code':r.returncode,'elapsed_seconds':time.time()-began},indent=2))
