from pathlib import Path
import shutil
S=Path('/root/prjs/tmp/quiet-maintenance-20261018')
BASE=Path('/root/prjs/releases/dialogue-fix-20261017/runtime')
if not (S/'candidate').exists():
 shutil.copytree(BASE,S/'candidate',ignore=shutil.ignore_patterns('models','__pycache__','*.pyc'))
 (S/'candidate/models').symlink_to(BASE/'models',target_is_directory=True)
for p in (S/'server').rglob('*.py'):
 dest=S/'candidate'/p.relative_to(S/'server');shutil.copy2(p,dest)
shutil.copytree('/root/prjs/tmp/dialogue-fix-20261017/candidate/test',S/'candidate/test',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
shutil.copy2(S/'test_quiet_maintenance.py',S/'candidate/test/test_quiet_maintenance.py')
runner=(S/'regression_template.py').read_text()
runner=runner.replace("names=['test_dialogue_fix_20261017'","names=['test_quiet_maintenance','test_person_memory_recovery','test_dialogue_fix_20261017'")
(S/'run_regression.py').write_text(runner)
