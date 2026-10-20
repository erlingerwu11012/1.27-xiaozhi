"""Run on SSH host AFTER review-service access resumes, inside isolated candidate.

No paid API calls, no production DB connection, no deployment. A later phase
must additionally run MySQL concurrency, Java, Python and Vue regression suites.
"""
from pathlib import Path
import json
import os
import subprocess

ROOT=Path('/root/prjs/tmp/hardware-billing70-20261001')
CAND=ROOT/'candidate/gateway'
assert str(CAND.resolve()).startswith('/root/prjs/tmp/hardware-billing70-20261001/')
logs=ROOT/'tests';logs.mkdir(exist_ok=True)
env=dict(os.environ)
env['PATH']='/usr/local/go/bin:'+env.get('PATH','')
# No production configuration or SQL DSN is inherited by these tests.
for key in list(env):
    if any(word in key.upper() for word in ['SQL_DSN','API_KEY','ACCESS_KEY','SERVICE_KEY','ADMIN_TOKEN']):env.pop(key,None)
results=[]
for label,args in [
    ('format',['gofmt','-w','hardwarebilling','relay/model/misc.go','relay/adaptor/ali/model.go','relay/adaptor/ali/main.go','relay/adaptor/openai/main.go']),
    ('ledger-unit',['go','test','./hardwarebilling','-count=1','-v']),
    ('actual-meter-adaptors',['go','test','./relay/adaptor/ali','./relay/adaptor/openai','-count=1']),
]:
    with (logs/(label+'.log')).open('w') as stream:
        done=subprocess.run(args,cwd=CAND,env=env,stdout=stream,stderr=subprocess.STDOUT)
    results.append({'test':label,'exit_code':done.returncode})
    print(json.dumps(results[-1]),flush=True)
    if done.returncode:break
(logs/'candidate-go-results.json').write_text(json.dumps({'results':results,'upstream_calls':0,'cost_cny':'0','production_changed':False},indent=2))
if any(x['exit_code'] for x in results):raise SystemExit(1)
