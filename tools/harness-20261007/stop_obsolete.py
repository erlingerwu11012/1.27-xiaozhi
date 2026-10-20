"""Stop only verified detached workers for an explicitly named evidence run."""
import argparse,json,os,signal,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('frozen');p.add_argument('--reason',required=True);a=p.parse_args()
stage=Path(__file__).resolve().parent
assert a.frozen.startswith('frozen-') and '/' not in a.frozen and chr(92) not in a.frozen
old=stage/a.frozen
assert old.resolve().is_relative_to(stage) and (old/'jobs.json').is_file()
stopped=[]
for job in json.loads((old/'jobs.json').read_text())['jobs']:
    pid=job['pid'];proc=Path('/proc')/str(pid)
    if not proc.exists():continue
    cmd=proc.joinpath('cmdline').read_bytes().split(b'\0')
    if str(stage/'launch_tests.py').encode() in cmd and a.frozen.encode() in cmd and os.getpgid(pid)==pid:
        os.killpg(pid,signal.SIGTERM);stopped.append(pid)
(old/'interrupted.json').write_text(json.dumps({'timestamp':time.time(),'reason':a.reason,'stopped_worker_pids':stopped},indent=2))
print(json.dumps({'isolated_test_processes_stopped':stopped,'production_untouched':True}))
