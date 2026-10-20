"""Upload reviewed source changes only; never include any mutable test ledger."""
from pathlib import Path
import hashlib,json,subprocess,tarfile
S=Path(__file__).resolve().parent
baseline=json.loads((S/'baseline/source-manifest.json').read_text(encoding='utf-8'))['files']
with tarfile.open(S/'source-delta.tgz','w:gz') as archive:
    for path in (S/'work').rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix=='.pyc':continue
        rel=path.relative_to(S/'work').as_posix()
        if baseline.get(rel.replace('/', '\\'),baseline.get(rel))==hashlib.sha256(path.read_bytes()).hexdigest():continue
        archive.add(path,arcname=path.relative_to(S).as_posix())
    for path in (S/'java').rglob('*.java'):archive.add(path,arcname=path.relative_to(S).as_posix())
    for path in (S/'baseline/java').rglob('*.java'):archive.add(path,arcname=path.relative_to(S).as_posix())
    for name in ['cases-followup.json','cases-followup.sha256']:archive.add(S/name,arcname=name)
    for path in S.glob('*.py'):
        if path.name not in {'budget.py','sync_candidate.py'}:archive.add(path,arcname=path.name)
subprocess.run(['scp','-q',str(S/'source-delta.tgz'),'root@121.40.239.140:/root/prjs/tmp/hardware-followup-20261013/source-delta.tgz'],check=True,timeout=60)
print('delta_uploaded_bytes', (S/'source-delta.tgz').stat().st_size)
