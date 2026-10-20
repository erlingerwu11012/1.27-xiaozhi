from pathlib import Path
import sys,subprocess,tarfile
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s))
with tarfile.open(s/'source-delta.tgz') as a:
 assert all((s/m.name).resolve().is_relative_to(s) and 'budget.sqlite3' not in m.name for m in a.getmembers());a.extractall(s,filter='data')
import unittest
from test_followup import Followup,BudgetResult
suite=unittest.TestSuite(Followup(n) for n in ['test_negative_exit_is_not_a_goal','test_memory_fact_is_not_a_lexical_note_goal','test_verified_confirmation_scope','test_missing_semantic_fields_never_dispatch'])
assert unittest.TextTestRunner(verbosity=2,resultclass=BudgetResult).run(suite).wasSuccessful()
with (s/'development05.log').open('x') as log:r=subprocess.run([sys.executable,str(s/'run_dialogues.py'),'--name','development05','--mode','development','--corpus','cases-followup'],cwd=s,stdout=log,stderr=subprocess.STDOUT)
print('exit',r.returncode);print('\n'.join((s/'development05.log').read_text().splitlines()[-12:]))
