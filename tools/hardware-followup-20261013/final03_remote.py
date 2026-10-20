from pathlib import Path
import subprocess,sys,tarfile,unittest
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
from test_followup import Followup,BudgetResult
assert unittest.TextTestRunner(verbosity=2,resultclass=BudgetResult).run(Followup('test_pending_query_is_a_live_list_read')).wasSuccessful()
with (s/'final03.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'run_dialogues.py'),'--name','final03','--mode','final','--corpus','cases-followup'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('final',r.returncode);print('\n'.join((s/'final03.log').read_text().splitlines()[-12:]))
