import hashlib,json,os,py_compile,shutil,subprocess,time
from pathlib import Path
stage=Path(__file__).parent
rel='main/xiaozhi-server/core/handle/textHandler/reminderEventMessageHandler.py'
old=next(r for r in json.loads((stage/'production-backup/deployment.json').read_text())['manifest'] if r['path']==rel)
new=next(r for r in json.loads((stage/'manifest.json').read_text()) if r['path']==rel)
dst=Path('/root/prjs/xiaozhi-esp32-server')/rel;src=stage/'candidate'/rel
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(dst)==old['candidate_sha256'] and sha(src)==new['candidate_sha256']
results=json.loads((stage/'test-results.json').read_text());assert all(r['passed'] for r in results)
py_compile.compile(str(src),doraise=True)
shutil.copy2(dst,stage/'production-backup/handler-before-protocol-correction.py')
temp=dst.with_suffix('.new.py');shutil.copy2(src,temp);os.replace(temp,dst)
subprocess.run(['pm2','restart','xiaozhi-server'],stdout=subprocess.DEVNULL,check=True)
result={'handler_correction':True,'new_sha256':new['candidate_sha256'],'deployed_at':time.strftime('%Y-%m-%d %H:%M:%S%z')}
(stage/'handler-correction-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
