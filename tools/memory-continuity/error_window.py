import json,subprocess,time
from pathlib import Path
out=Path('/root/prjs/tmp/memory-continuity-release-20260930');pm=json.loads(subprocess.check_output(['pm2','jlist'],text=True))
logs={p['name']:Path(p['pm2_env']['pm_err_log_path']) for p in pm if p['name'] in ('manager-api','xiaozhi-server')};offset={name:p.stat().st_size for name,p in logs.items()}
time.sleep(30)
counts={}
for name,p in logs.items():
 with p.open('rb') as stream:stream.seek(offset[name]);text=stream.read().decode(errors='replace')
 counts[name]={'new_error_bytes':len(text.encode()),'new_tracebacks':text.count('Traceback'),'retention_deferrals':text.count('archive retention deferred'),'memory_deferrals':text.count('memory worker deferred')}
result={'manual_observation_seconds':30,'errors':counts,'passed':all(not c['new_tracebacks'] and not c['retention_deferrals'] and not c['memory_deferrals'] for c in counts.values())}
(out/'error-window.json').write_text(json.dumps(result));print(json.dumps(result))
