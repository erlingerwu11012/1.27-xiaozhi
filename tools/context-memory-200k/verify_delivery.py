"""Offline verification of delivered sources and sanitized acceptance records."""
from pathlib import Path
import hashlib,json,tarfile

root=Path(__file__).resolve().parents[2]
delivery=Path(__file__).resolve().parent/'delivery'
manifest=json.loads((delivery/'manifest.json').read_text(encoding='utf-8'))
with tarfile.open(delivery/'overlay.tar.gz','r:gz') as archive:
    entries=archive.getmembers()
    assert all(entry.isfile() and not entry.name.startswith('/') and '..' not in Path(entry.name).parts for entry in entries)
    assert {entry.name for entry in entries}==set(manifest)
    for entry in entries:
        content=archive.extractfile(entry).read()
        assert hashlib.sha256(content).hexdigest()==manifest[entry.name],entry.name
        if entry.name.endswith('.py'):compile(content,entry.name,'exec')
report=json.loads((delivery/'delivery-report.json').read_text(encoding='utf-8'))
java=report['java']
assert java['failures']==java['errors']==java['skipped']==0
tests=java['tests']+sum(report['voice'].values())+sum(report['regression'].values())
assert tests==378
assert report['health']['healthy'] and report['health']['portrait_disabled_verified']
assert report['health']['source_delivery']['candidate_files_verified']==len(manifest)==34
assert report['health']['source_delivery']['manifest_sha256']==hashlib.sha256((delivery/'manifest.json').read_bytes()).hexdigest()
assert report['boot']['passed'] and report['boot']['protected_routes']==7
for key in ('real_model','cloud','model_tools','frontend'):assert report[key]['passed']
for name in ('published.json','final-patch-published.json','business-patch-published.json'):assert json.loads((delivery/name).read_text())['published']
ui=json.loads((delivery/'frontend-check.json').read_text());assert ui['passed'] and not ui['pageErrors']
visual=json.loads((delivery/'visual-check.json').read_text());assert len(visual['checks'])==12 and not visual['errors']
assert all(not row['outside'] and not row['overflow'] for row in visual['checks'])
for file in Path(__file__).resolve().parent.glob('*.py'):compile(file.read_bytes(),str(file),'exec')
proof={'verified':True,'source_files':len(manifest),'production_files':report['health']['production_source_hashes_verified'],
    'automated_tests':tests,'boot_protected_routes':7,'visual_scenarios':12,
    'hardware_acceptance':'pending user testing','portrait_enabled':False,'firmware_ota':False,
    'gateway_stream_cached_tokens':'unknown','published_at':report['published']['at'],'final_patch_at':report['final_patch']['at'],
    'business_patch_at':report['business_patch']['at'],'last_manual_health_at':report['health']['at']}
(delivery/'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
checksums={file.name:hashlib.sha256(file.read_bytes()).hexdigest() for file in sorted(delivery.iterdir()) if file.is_file() and file.name!='checksums.json'}
(delivery/'checksums.json').write_text(json.dumps(checksums,indent=2),encoding='utf-8')
print(json.dumps(proof,ensure_ascii=False))
