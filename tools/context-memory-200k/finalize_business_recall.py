"""Publish verified Java-only business recall without changing schema or config."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,time,urllib.request
prod=Path('/root/prjs/xiaozhi-esp32-server');candidate=Path('/root/prjs/tmp/bailian-memory-product')
release=Path('/root/prjs/tmp/context-memory-release-20260929');folder=release/'final-business-recall'
assert not (folder/'published.json').exists(),'already_published'
old=json.loads((release/'manifest.json').read_text());new=json.loads((release/'delivery-manifest.json').read_text())
assert json.loads((release/'tests.json').read_text())['passed']
assert json.loads(Path('/tmp/bailian-memory-boot-smoke-result.json').read_text())['passed']
source='main/manager-api/src/main/java/xiaozhi/modules/personmemory/RecentArchiveService.java'
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
for name,expected in new.items():assert digest(candidate/name)==expected,'candidate_mismatch'
for name,expected in old.items():
    if '/src/test/' not in name and '/test/' not in name:assert digest(prod/name)==expected,'production_concurrent_change'
jar=prod/'main/manager-api/target/xiaozhi-esp32-api.jar'
base=json.loads((release/'published.json').read_text());assert digest(jar)==base['jar_sha256'],'production_jar_changed'
folder.mkdir(exist_ok=True);shutil.copy2(prod/source,folder/'RecentArchiveService.java');shutil.copy2(jar,folder/'manager-api-before.jar')
def install(before,after):
    temp=after.with_name(after.name+'.business-next');shutil.copy2(before,temp);os.replace(temp,after)
def ready():
    for _ in range(150):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8002/xiaozhi/user/pub-config',timeout=2) as response:
                if response.status==200 and json.loads(response.read()).get('code')==0:return True
        except Exception:pass
        time.sleep(.5)
    return False
try:
    subprocess.run(['pm2','stop','manager-api'],capture_output=True,check=True)
    install(candidate/source,prod/source);install(candidate/'main/manager-api/target/xiaozhi-esp32-api.jar',jar)
    subprocess.run(['pm2','restart','manager-api'],capture_output=True,check=True)
    assert ready(),'manager_not_ready'
except Exception:
    install(folder/'RecentArchiveService.java',prod/source);install(folder/'manager-api-before.jar',jar)
    subprocess.run(['pm2','restart','manager-api'],capture_output=True)
    raise
(release/'manifest.json').write_text(json.dumps(new,indent=2))
report={'published':True,'at':time.strftime('%Y-%m-%d %H:%M:%S %z'),'source':source,'source_sha256':digest(prod/source),
    'jar_sha256':digest(jar),'business_recall':True,'schema_changed':False,'config_changed':False,'firmware_ota':False}
(folder/'published.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
