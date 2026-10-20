import hashlib,json,os,shutil,socket,subprocess,time
from pathlib import Path
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005');PROD=Path('/root/prjs/xiaozhi-esp32-server');CAND=OUT/'worktree'
receipt=json.loads((OUT/'deployment-receipt.json').read_text())
assert receipt['deployed']
assert json.loads((OUT/'regression.json').read_text())['run']==214
assert json.loads((OUT/'regression.json').read_text())['success']
assert json.loads((OUT/'candidate-runtime-acceptance.json').read_text())['actual_mcp_executions']==3
names=['main/xiaozhi-server/core/utils/operation_control.py','main/xiaozhi-server/test/test_natural_tool_failure_regression.py','main/xiaozhi-server/test/test_operation_control.py']
backup=OUT/'postrelease-mcp-backup';backup.mkdir(exist_ok=False)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for name in names:
 p=PROD/name
 if name in receipt['source_files']:assert sha(p)==receipt['source_files'][name]['after']
 target=backup/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
 original=Path(receipt['backup'])/'source'/name
 if name not in receipt['source_files']:
  original.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,original)
  receipt['source_files'][name]={'before':sha(p)}
def copy(src,dest):
 tmp=dest.with_name(dest.name+'.mcp-new');shutil.copy2(src,tmp);os.replace(tmp,dest)
try:
 for name in names:copy(CAND/name,PROD/name)
 subprocess.run(['pm2','restart','xiaozhi-server'],check=True,capture_output=True,timeout=30)
 for _ in range(30):
  try:
   with socket.create_connection(('127.0.0.1',8000),timeout=2):break
  except OSError:time.sleep(1)
 else:raise RuntimeError('ws_listener_missing')
 for name in names:receipt['source_files'][name]['after']=sha(PROD/name)
 receipt['mcp_read_only_routing_patch']=True
 (OUT/'deployment-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
 print(json.dumps({'mcp_patch_deployed':True,'source_files':len(receipt['source_files']),'ws_port':8000}))
except Exception:
 for name in names:copy(backup/name,PROD/name)
 subprocess.run(['pm2','restart','xiaozhi-server'],capture_output=True,timeout=30)
 raise RuntimeError('mcp_patch_failed_rolled_back') from None
