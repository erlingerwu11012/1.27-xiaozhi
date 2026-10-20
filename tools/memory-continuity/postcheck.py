import json,subprocess,urllib.request,hashlib,time
from pathlib import Path
import live_auth as auth
out=Path('/root/prjs/tmp/memory-continuity-release-20260930');prod=Path('/root/prjs/xiaozhi-esp32-server')
manifest=json.loads((out/'manifest.json').read_text())
assert all(hashlib.sha256((prod/name).read_bytes()).hexdigest()==digest for name,digest in manifest.items())
pm=json.loads(subprocess.check_output(['pm2','jlist'],text=True))
services={p['name']:p['pm2_env']['status'] for p in pm if p['name'] in ('manager-api','xiaozhi-server')}
assert len(services)==2 and all(s=='online' for s in services.values())
health={}
for url in ('https://api.realecho.cn/xiaozhi/user/pub-config','https://www.realecho.cn','https://realecho.cn','http://127.0.0.1:8006/openapi.json'):
 with urllib.request.urlopen(url,timeout=10) as response:health[url]=response.status
counts=json.loads(auth.sql("SELECT JSON_OBJECT('audio_rows',(SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_agent_chat_audio),'audio_bytes',(SELECT COALESCE(SUM(OCTET_LENGTH(audio)),0) FROM xiaozhi_esp32_server.ai_agent_chat_audio),'archive_rows',(SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_agent_chat_history),'pending_material',(SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_person_material),'pending_user_tokens',(SELECT COALESCE(SUM(user_tokens),0) FROM xiaozhi_esp32_server.ai_person_material WHERE kind='dialogue'),'cleanup_pending',(SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_identity_cleanup WHERE state<>'complete'),'extraction_pending',(SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_memory_task WHERE state IN('pending','submitting','accepted','review','retry')));"))
old_audio=int(auth.sql("SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_agent_chat_history WHERE audio_id IS NOT NULL AND (chat_type<>1 OR created_at<DATE_SUB(NOW(),INTERVAL 72 HOUR));"))
assert old_audio==0,'expired_audio_not_cleaned'
errors={}
for service in ('manager-api','xiaozhi-server'):
 p=next(p for p in pm if p['name']==service)
 error=Path(p['pm2_env']['pm_err_log_path'])
 # Only aggregate recent errors; never output audio/dialogue or credentials.
 recent=subprocess.check_output(['tail','-n','500',str(error)],text=True,errors='replace').splitlines() if error.exists() else []
 errors[service]={word:sum(word in line for line in recent) for word in ('Traceback','archive retention deferred','memory worker deferred')}
result={'passed':True,'at':time.strftime('%Y-%m-%d %H:%M:%S %z'),'services':services,'health':health,'counts':counts,'expired_audio_references':old_audio,'error_tail_aggregates':errors,'portraits':False,'physical_device_pending':True,'actual_next_0300_window':'not_yet_observed'}
(out/'postcheck.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
