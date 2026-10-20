from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parent))
from budget import Budget
b=Budget(Path(__file__).parent/'local-budget.sqlite3');b.reserve('case','vision_credentials_production_host_suite')
import subprocess
r=subprocess.run([sys.executable,'tools/run_vision_credentials_host_test.py'],capture_output=True,text=True)
(Path(__file__).parent/'vision-host.log').write_text(r.stdout+r.stderr,encoding='utf-8');print(r.stdout[-1500:]);print(r.stderr[-800:] if r.returncode else '');raise SystemExit(r.returncode)
