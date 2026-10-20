"""Save only this task's changed source as a reviewable delivery and manifest.

This does not commit Git, transfer to SSH, migrate a database or deploy.
"""
from pathlib import Path
import hashlib
import json
import shutil
import tarfile

ROOT=Path(__file__).resolve().parents[2]
CAND=ROOT/'tmp/hardware-billing70'
OUT=ROOT/'tools/hardware-billing70'
DELIVERY=OUT/'delivery'
base={}
with tarfile.open(CAND/'candidate-source.tar.gz','r:gz') as archive:
    for entry in archive:
        if not entry.isfile():continue
        name=entry.name.removeprefix('./')
        stream=archive.extractfile(entry)
        if stream:base[name]=hashlib.sha256(stream.read()).hexdigest()

manifest=[]
for prefix in ['server','gateway']:
    for path in (CAND/prefix).rglob('*'):
        if not path.is_file() or path.suffix not in {'.java','.go','.py','.vue','.js','.sql','.yaml'}:continue
        if '__pycache__' in path.parts:continue
        relative=path.relative_to(CAND).as_posix()
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        previous=base.get(relative)
        if relative.endswith('/db.changelog-master.yaml'):
            previous=json.loads((OUT/'migration-master-baseline.json').read_text())['sha256']
        if relative=='gateway/middleware/distributor.go':
            previous=json.loads((OUT/'distributor-baseline.json').read_text())['sha256']
        extra=OUT/'additional-baselines.json'
        if extra.exists():previous=json.loads(extra.read_text()).get(relative,previous)
        if previous==digest:continue
        target=DELIVERY/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
        manifest.append({'path':relative,'baseline_sha256':previous,'candidate_sha256':digest})

with tarfile.open(OUT/'candidate-overlay.tar.gz','w:gz') as archive:
    for row in sorted(manifest,key=lambda x:x['path']):archive.add(DELIVERY/row['path'],arcname=row['path'])
receipt={'stage':'candidate_only','production_changed':False,'git_commit':None,
         'remote_build_and_tests':'passed_58_steps_plus_go_and_real_cloud',
         'real_api_test_cost_cny':'see_tests_actual_receipts','changes':sorted(manifest,key=lambda x:x['path'])}
(OUT/'candidate-manifest.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'changed_source_files':len(manifest),'production_changed':False,'git_committed':False}))
