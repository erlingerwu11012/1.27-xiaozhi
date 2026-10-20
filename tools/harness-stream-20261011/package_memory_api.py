"""Preserve the running API package except the six reviewed memory classes."""
from pathlib import Path
import hashlib,json,os,time,zipfile

S=Path(__file__).parent
baseline=Path('/root/prjs/releases/hardware-repair-20261009/xiaozhi-esp32-api.jar')
compiled=S/'manager-api/target/xiaozhi-esp32-api.jar'
release=Path('/root/prjs/releases/harness-stream-20261012/xiaozhi-esp32-api.jar')
manifest=S/'memory-api-package26.json'
assert not manifest.exists(), 'Keep previous packaging evidence'
names=[
 'MemoryDailyWorker.class','PersonMemoryController$AddRequest.class',
 'PersonMemoryController$AnalysisResult.class','PersonMemoryController.class',
 'PersonMemoryService.class','RecentArchiveService.class',
]
selected={'BOOT-INF/classes/xiaozhi/modules/personmemory/'+n for n in names}
sha=lambda data:hashlib.sha256(data).hexdigest()
temporary=release.with_suffix('.memory26.tmp')
assert not temporary.exists()
with zipfile.ZipFile(baseline) as old,zipfile.ZipFile(compiled) as new:
 assert selected <= set(new.namelist())
 with zipfile.ZipFile(temporary,'w') as out:
  for info in old.infolist():out.writestr(info,new.read(info.filename) if info.filename in selected else old.read(info.filename))
  for name in sorted(selected-set(old.namelist())):out.writestr(new.getinfo(name),new.read(name))
with zipfile.ZipFile(baseline) as old,zipfile.ZipFile(temporary) as packed,zipfile.ZipFile(compiled) as new:
 assert set(packed.namelist())==set(old.namelist())|selected
 changed=[]
 for name in packed.namelist():
  data=packed.read(name)
  if name in selected:
   assert data==new.read(name)
   changed.append({'path':name,'sha256':sha(data)})
  else:assert data==old.read(name),name
 for name in ['BOOT-INF/classes/xiaozhi/modules/pay/service/HardwareBillingPolicy.class','BOOT-INF/classes/xiaozhi/modules/pay/service/impl/OneApiBindingServiceImpl.class']:
  assert packed.read(name)==old.read(name)
os.chmod(temporary,0o600)
os.replace(temporary,release)
evidence={'created':time.time(),'baseline':str(baseline),'baseline_sha256':sha(baseline.read_bytes()),'compiled_source':str(compiled),'compiled_sha256':sha(compiled.read_bytes()),'packaged':str(release),'packaged_sha256':sha(release.read_bytes()),'selected_memory_classes':changed,'all_other_entries_identical_to_production':True,'production_processes_changed':False,'startup_validation':'pending'}
manifest.write_text(json.dumps(evidence,indent=2))
print(json.dumps({'memory_classes':len(changed),'all_other_entries_identical_to_production':True,'production_processes_changed':False,'startup_validation':'pending'}))
