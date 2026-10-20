import hashlib,json,shutil
from pathlib import Path
stage=Path(__file__).parent
name='config/assets/wakeup_words/83dca73ebd19180d2b8b39723dae401b.wav'
candidate=stage/'work/xiaozhi-server'/name
production=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')/name
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
baseline=json.loads((stage/'production-backup/deployment.json').read_text())['protected'][str(production)]
if sha(candidate)==baseline:shutil.copy2(candidate,stage/'private-backup/wakeup-before-deployment.wav')
out={'candidate_matches_original':sha(candidate)==baseline,'production_changed':sha(production)!=baseline}
import yaml
cache=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/data/.wakeup_words.yaml')
if cache.exists():
 row=(yaml.safe_load(cache.read_text()) or {}).get(production.stem,{})
 out['cache_time_matches_audio']=abs(float(row.get('time',0))-production.stat().st_mtime)<5
 out['cache_file_matches_audio']=str(row.get('file_path','')).endswith(name)
log=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/logs/pm2-out.log')
if log.exists():
 lines=log.read_text(errors='replace').splitlines()[-2000:]
 relevant=[line for line in lines if any(x in line for x in ('唤醒词响应','唤醒回复','更新唤醒','唤醒响应','wakeup_words'))]
 out['related_log_lines']=len(relevant)
 print(json.dumps(out));print('\n'.join(line[:320] for line in relevant[-8:]))
else:print(json.dumps(out))
