"""Publish verified execution/context/plain-speech fixes; keep default model and chat candidate unchanged."""
import hashlib,json,os,shutil,socket,subprocess,time
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import urlopen
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
PROD=Path('/root/prjs/xiaozhi-esp32-server');CAND=OUT/'worktree'
names=['main/xiaozhi-server/core/connection.py','main/xiaozhi-server/core/utils/tool_fact_reply.py',
       'main/xiaozhi-server/core/utils/dialogue.py','main/xiaozhi-server/core/utils/turn_context.py',
       'main/xiaozhi-server/core/providers/tools/server_mcp/mcp_executor.py',
       'main/xiaozhi-server/core/providers/tts/official/prompt.py',
       'main/xiaozhi-server/test/test_verified_tool_facts.py','main/xiaozhi-server/test/test_prompt_pipeline_v2.py']
reg=json.loads((OUT/'dialogue-fix-regression.json').read_text());assert reg['success'] and reg['run']==233
voice=json.loads((OUT/'dialogue-fix-voice-chain.json').read_text());assert voice['completed'] and all(c.get('time_reply_matches_receipt') for c in voice['cases'][2:])
assert subprocess.check_output(['git','-C',str(PROD),'rev-parse','HEAD'],text=True).strip().startswith('8d0e66ea')
assert not subprocess.check_output(['git','-C',str(PROD),'status','--porcelain','--untracked-files=no'],text=True).strip()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
before_guide=sha(PROD/'main/xiaozhi-server/core/utils/conversation_guidance.py')
backup=OUT/('verified-facts-backup-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'));backup.mkdir(mode=0o700)
manifest={}
for name in names:
 p=PROD/name;b=backup/name;b.parent.mkdir(parents=True,exist_ok=True)
 manifest[name]={'before':sha(p),'after':sha(CAND/name)}
 if p.exists():shutil.copy2(p,b)
def install(src,dst):
 dst.parent.mkdir(parents=True,exist_ok=True);tmp=dst.with_name(dst.name+'.facts-new');shutil.copy2(src,tmp);os.replace(tmp,dst)
def health():
 for _ in range(35):
  try:
   with socket.create_connection(('127.0.0.1',8000),timeout=2):pass
   with urlopen('http://127.0.0.1:8003/mcp/vision/explain',timeout=3) as r:assert r.status==200
   return
  except Exception:time.sleep(1)
 raise RuntimeError('service_not_ready')
try:
 for name in names:install(CAND/name,PROD/name)
 subprocess.run(['pm2','restart','xiaozhi-server'],check=True,capture_output=True,timeout=30);health()
 statuses={p['name']:p['pm2_env']['status'] for p in json.loads(subprocess.check_output(['pm2','jlist'],text=True)) if p['name'] in {'xiaozhi-server','manager-api','mcp-gateway'}}
 assert all(v=='online' for v in statuses.values())
 public={}
 for url in ['https://www.realecho.cn/','https://api.realecho.cn/mcp/vision/explain']:
  with urlopen(url,timeout=15) as r:public[url]=r.status;assert r.status==200
 assert sha(PROD/'main/xiaozhi-server/core/utils/conversation_guidance.py')==before_guide
 result={'deployed':True,'scope':'verified tool receipts, context labels and plain speech only','default_model_changed':False,
         'candidate_chat_rules_deployed':False,'user_personalities_changed':False,'secondary_rewrite':False,
         'physical_voice_test':False,'backup':str(backup),'files':manifest,'processes':statuses,'public_http':public}
 (OUT/'dialogue-fix-deployment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(json.dumps({k:v for k,v in result.items() if k not in {'files','backup'}},ensure_ascii=False))
except Exception:
 for name in names:
  b=backup/name;p=PROD/name
  if b.exists():install(b,p)
  elif manifest[name]['before'] is None and p.exists():p.unlink()
 subprocess.run(['pm2','restart','xiaozhi-server'],capture_output=True,timeout=30)
 raise RuntimeError('facts_release_failed_rolled_back') from None
