from pathlib import Path
import tarfile
stage=Path(__file__).parent
with tarfile.open(stage/'changes.tgz','w:gz') as archive:
 for path in stage.glob('*.py'):
  if path.name not in {'implement.py','manifest_migrate.py','pack_changes.py'}:archive.add(path,arcname=path.relative_to(stage))
 for path in (stage/'work').rglob('*.py'):archive.add(path,arcname=path.relative_to(stage))
 for path in (stage/'java').glob('*.java'):archive.add(path,arcname=path.relative_to(stage))
 for name in ['cases-v2.json','cases-v2.sha256','fixture-corrections.json','work/agent-base-prompt-v2.txt']:
  if (stage/name).exists():archive.add(stage/name,arcname=name)
print((stage/'changes.tgz').stat().st_size)
