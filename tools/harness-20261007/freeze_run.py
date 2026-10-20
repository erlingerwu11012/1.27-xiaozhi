"""Freeze source, fixtures and runner on the server; never touch production."""
import hashlib,json,os,shutil,sys
from pathlib import Path
stage=Path(__file__).parent
name=sys.argv[1]
if not name.startswith('frozen-') or '/' in name or '\\' in name:raise ValueError('invalid run name')
target=stage/name
target.mkdir(mode=0o700)
shutil.copytree(stage/'work',target/'work',symlinks=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','operations.sqlite3*'))
for file in list(stage.glob('*.py'))+[stage/'pack.json',stage/'candidate-manifest.json']+([stage/'budget-plan.json'] if (stage/'budget-plan.json').exists() else []):
    shutil.copy2(file,target/file.name)
holdout=(stage/sys.argv[2]).resolve() if len(sys.argv)>2 else stage/'holdout.json'
assert holdout.is_relative_to(stage.resolve())
if holdout.exists():shutil.copy2(holdout,target/'holdout.json')
(target/'private-backup').symlink_to(stage/'private-backup',target_is_directory=True)
manifest={str(p.relative_to(target)):hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*.py')}
if (target/'budget-plan.json').exists():manifest['budget-plan.json']=hashlib.sha256((target/'budget-plan.json').read_bytes()).hexdigest()
manifest['pack.json']=hashlib.sha256((target/'pack.json').read_bytes()).hexdigest()
if (target/'holdout.json').exists():manifest['holdout.json']=hashlib.sha256((target/'holdout.json').read_bytes()).hexdigest()
(target/'frozen-hashes.json').write_text(json.dumps(manifest,sort_keys=True,indent=2))
print(json.dumps({'frozen_directory':str(target),'files':len(manifest)}))
