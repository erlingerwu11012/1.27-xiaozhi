from pathlib import Path
import json,time,subprocess,os
S=Path(__file__).parent
for n in ['final-results.jsonl','final-freeze.json','final-console.log','final-summary.json']:
 p=S/n
 if p.exists():
  dest=S/('aborted-fourth-'+n);assert not dest.exists();p.rename(dest)
(S/'aborted-fourth-note.json').write_text(json.dumps({'reason':'Stopped at 249 cases after explicit quoted note was incorrectly planned as reminder; failure preserved. Direct note decision now verified over actual MCP transport without a model call.','time':time.time()}))
f=(S/'final-console.log').open('w');p=subprocess.Popen(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python','-u',str(S/'run_final.py')],cwd=S,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
(S/'final-pid.json').write_text(json.dumps({'pid':p.pid,'started_at':time.time()}));print(json.dumps({'started':p.pid}))
