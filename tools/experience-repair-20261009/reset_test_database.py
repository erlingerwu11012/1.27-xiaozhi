import json,os,signal,subprocess,sys,time
from pathlib import Path
S=Path(__file__).parent
try:os.kill(json.loads((S/'candidate-manager-pid.json').read_text())['pid'],signal.SIGTERM)
except ProcessLookupError:pass
time.sleep(2)
f=S/'isolated-db-ready.json';f.rename(S/'isolated-db-ready-before-api.json')
for script in ['prepare_database.py','fix_isolated_migrations.py','start_api.py']:
 subprocess.run([sys.executable,str(S/script)],check=True)
