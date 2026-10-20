"""Manual post-release inspection; aggregate metadata only, no recurring automation."""
from pathlib import Path
import json,subprocess,sys,os,re,hashlib,xml.etree.ElementTree as ET
from datetime import datetime
release=Path('/root/prjs/tmp/context-memory-release-20260929')
prod=Path('/root/prjs/xiaozhi-esp32-server')
published=json.loads((release/'published.json').read_text());assert published['published']
result=json.loads(subprocess.run(['python3','/tmp/observe_release.py'],capture_output=True,text=True,check=True).stdout)
sys.path.insert(0,str(prod/'main/xiaozhi-server'))
from unittest.mock import MagicMock
from config import logger
logger.setup_logging=lambda:MagicMock()
from config.config_loader import load_config
from core.utils.dialogue import Dialogue
from core.utils.context_window import ContextWindow
config=load_config();window=ContextWindow(Dialogue(),config)
result['context']={'prepare':window.prepare,'trigger':window.trigger,'target':window.target,'limit':window.limit,'summary_target':window.summary_target,'summary_max':window.summary_max,'batch':window.batch}
assert result['context']=={'prepare':160000,'trigger':180000,'target':50000,'limit':200000,'summary_target':3000,'summary_max':6000,'batch':24000}
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(q):return subprocess.run(mysql,input=q,text=True,capture_output=True,check=True).stdout.strip()
result['new_schema']={'changeset':sql("SELECT COUNT(*) FROM xiaozhi_esp32_server.DATABASECHANGELOG WHERE ID='202609292100-context-archive';"),'archive_columns':sql("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='xiaozhi_esp32_server' AND TABLE_NAME='ai_agent_chat_history' AND COLUMN_NAME IN('account_id','person_id','identity_status','turn_id','event_id','directory_version','default_generation','recall_allowed');")}
assert result['new_schema']=={'changeset':'1','archive_columns':'8'}
result['cleanup_stages']=sql("SELECT state,cloud_done,portrait_done,local_done,COUNT(*) FROM xiaozhi_esp32_server.ai_identity_cleanup GROUP BY state,cloud_done,portrait_done,local_done;")
result['cleanup_device_acknowledgments']=sql("SELECT COUNT(*),SUM(confirmed_at IS NOT NULL) FROM xiaozhi_esp32_server.ai_identity_cleanup_device;")
pm=json.loads(subprocess.run(['pm2','jlist'],capture_output=True,text=True,check=True).stdout)
manager=next(p for p in pm if p['name']=='manager-api')
environment=dict(x.decode().split('=',1) for x in Path('/proc/'+str(manager['pid'])+'/environ').read_bytes().split(b'\0') if b'=' in x)
assert environment.get('MEMORY_PORTRAIT_ENABLED')=='false'
result['portrait_disabled_verified']=True
final_patch=json.loads((release/'final-summary-revision/published.json').read_text())
assert final_patch['published']
manifest=json.loads((release/'manifest.json').read_text())
source_files=[name for name in manifest if '/test/' not in name and '/src/test/' not in name]
assert all(hashlib.sha256((prod/name).read_bytes()).hexdigest()==manifest[name] for name in source_files)
business_patch_file=release/'final-business-recall/published.json'
business_patch=json.loads(business_patch_file.read_text()) if business_patch_file.exists() else None
if business_patch:assert business_patch['published']
assert hashlib.sha256((prod/'main/manager-api/target/xiaozhi-esp32-api.jar').read_bytes()).hexdigest()==(business_patch or published)['jar_sha256']
result['production_source_hashes_verified']=len(source_files)
delivery_manifest=release/'delivery-manifest.json'
if delivery_manifest.exists():
    final_manifest=json.loads(delivery_manifest.read_text())
    candidate=Path('/root/prjs/tmp/bailian-memory-product')
    assert all(hashlib.sha256((candidate/name).read_bytes()).hexdigest()==digest for name,digest in final_manifest.items())
    assert all(final_manifest[name]==manifest[name] for name in source_files)
    result['source_delivery']={'candidate_files_verified':len(final_manifest),'manifest_sha256':hashlib.sha256(delivery_manifest.read_bytes()).hexdigest()}
since=datetime.strptime(published['at'],'%Y-%m-%d %H:%M:%S %z').replace(tzinfo=None)
result['new_errors']={}
for item in pm:
    if item['name'] not in ('xiaozhi-server','manager-api'):continue
    error=Path(item['pm2_env']['pm_err_log_path'])
    recent=error.read_text(errors='replace')[-150000:] if error.exists() else ''
    lines=[]
    for line in recent.splitlines():
        stamp=re.search(r'(\d{6} \d{2}:\d{2}:\d{2}|\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})',line)
        if not stamp:continue
        value=stamp[0].replace('T',' ')
        try:at=datetime.strptime(value,'%y%m%d %H:%M:%S' if len(value)==15 else '%Y-%m-%d %H:%M:%S')
        except ValueError:continue
        if at>=since:lines.append(line)
    result['new_errors'][item['name']]=sum('ERROR' in line or 'Traceback' in line for line in lines)
result['manual_only']=True;result['automatic_observation_recreated']=False
(release/'health.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
assert result['healthy'] and result['counts']['portrait_rows']=='0'
# Test counts and result records contain only synthetic input aggregates.
java={'tests':0,'failures':0,'errors':0,'skipped':0}
for file in (Path('/root/prjs/tmp/bailian-memory-product/main/manager-api/target/surefire-reports')).glob('TEST-*.xml'):
    node=ET.parse(file).getroot()
    for field in java:java[field]+=int(node.attrib.get(field,0))
voice={}
for file in release.glob('voice-test_*.log'):
    count=re.search(r'Ran (\d+) tests?',file.read_text(errors='replace'))
    if count:voice[file.stem]=int(count[1])
regression={}
for file in Path('/tmp').glob('bailian-memory-regression-*.log'):
    count=re.search(r'Ran (\d+) tests?',file.read_text(errors='replace'))
    if count:regression[file.stem]=int(count[1])
report={'java':java,'voice':voice,'regression':regression,'published':published,'final_patch':final_patch,'health':result}
if business_patch:report['business_patch']=business_patch
for name,path in [('real_model',release/'real-model.json'),('cloud',Path('/tmp/bailian-memory-live-cloud-result.json')),('model_tools',Path('/tmp/bailian-memory-model-tool-result.json')),('boot',Path('/tmp/bailian-memory-boot-smoke-result.json')),('frontend',release/'frontend-check.json')]:
    report[name]=json.loads(path.read_text())
(release/'delivery-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'healthy':result['healthy'],'context':result['context'],'new_schema':result['new_schema'],'portrait_disabled':True,'new_error_counts':result['new_errors'],'cleanup_stages':result['cleanup_stages'],'cleanup_acknowledgments':result['cleanup_device_acknowledgments'],'java':java,'voice_tests':sum(voice.values()),'regression_tests':sum(regression.values()),'report':str(release/'delivery-report.json')},ensure_ascii=False))
