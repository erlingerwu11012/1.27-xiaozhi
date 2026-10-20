"""Save reviewable source diffs outside ignored candidate mirrors."""
import difflib
import hashlib
import json
import tarfile
from pathlib import Path

root=Path(__file__).resolve().parents[2]
work=root/'tmp/bailian-memory-product'
destination=root/'tools/bailian-memory-product/delivery'
destination.mkdir(exist_ok=True)
manifest={}
for component in ['server','gateway']:
    changes=json.loads((work/(component+'-changes.json')).read_text())
    with tarfile.open(work/(component+'-source.tar.gz')) as archive:
        originals={item.name:archive.extractfile(item).read() for item in archive.getmembers() if item.isfile() and item.name in changes}
    chunks=[]
    for name in sorted(changes):
        current=(work/component/name).read_bytes()
        assert hashlib.sha256(current).hexdigest()==changes[name]
        before=originals.get(name,b'').decode('utf-8-sig').splitlines(keepends=True)
        after=current.decode('utf-8-sig').splitlines(keepends=True)
        before=[line.rstrip('\r\n')+'\n' for line in before]
        after=[line.rstrip('\r\n')+'\n' for line in after]
        chunks.extend(difflib.unified_diff(before,after,fromfile='a/'+name,tofile='b/'+name))
    patch=destination/(component+'.patch');patch.write_text(''.join(chunks),encoding='utf-8',newline='\n')
    manifest[component]={'files':changes,'base_files':{name:hashlib.sha256(originals[name]).hexdigest() if name in originals else None for name in changes},'patch_sha256':hashlib.sha256(patch.read_bytes()).hexdigest()}
baseline=json.loads((work/'firmware-baseline.json').read_text())
firmware={}
for path in (root/'main').rglob('*'):
    if path.is_file() and path.suffix in {'.cc','.h','.cpp','.txt'}:
        name=path.relative_to(root).as_posix();digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if baseline['sha256'].get(name)!=digest:firmware[name]=digest
manifest['firmware']={'base_head':baseline['head'],'changed_since_task_start':firmware,'preexisting_changes_preserved':True}
compression_override=destination/'context-compress-100k.yaml'
if compression_override.exists():
    manifest['configuration']={'context_compress':{'max_context_tokens':125000,'compact_threshold':0.8,'actual_summary_trigger':100000},'override_file':compression_override.name,'override_sha256':hashlib.sha256(compression_override.read_bytes()).hexdigest(),'compression_algorithm_changed':False}
(destination/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'source_patches':{key:len(manifest[key]['files']) for key in ['server','gateway']},'firmware_changes':len(firmware)}))
