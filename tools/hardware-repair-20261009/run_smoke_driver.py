import subprocess,sys
from pathlib import Path
S=Path(__file__).parent
for script in ['recover_test_api.py','wire_smoke.py']:
 subprocess.run([sys.executable,str(S/script)],check=True)
