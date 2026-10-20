"""Read-only post-release observation; no user memory bodies are collected."""
import json
import subprocess
import time
import urllib.request
from pathlib import Path

release=Path('/root/prjs/tmp/bailian-memory-release-20260929')
published=json.loads((release/'published.json').read_text())
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(query):return subprocess.run(mysql,input=query,text=True,capture_output=True,check=True).stdout.strip()
pm=json.loads(subprocess.run(['pm2','jlist'],capture_output=True,text=True,check=True).stdout)
report={'at':time.strftime('%Y-%m-%d %H:%M:%S %z'),'published':published['published'],'services':{p['name']:p['pm2_env']['status'] for p in pm},'http':{},'firmware_ota':False,'portraits_enabled':False}
for name,url in {'gateway':'http://127.0.0.1:3011/healthz','face':'http://127.0.0.1:8765/health','manager':'https://api.realecho.cn/xiaozhi/user/pub-config','frontend':'https://www.realecho.cn/'}.items():
    try:
        with urllib.request.urlopen(url,timeout=5) as response:report['http'][name]=response.status
    except Exception as error:report['http'][name]=type(error).__name__
queries={
 'identity_modes':"SELECT mode,COUNT(*) FROM xiaozhi_esp32_server.ai_account_identity_state GROUP BY mode;",
 'memory_tasks':"SELECT state,COUNT(*) FROM xiaozhi_esp32_server.ai_memory_task GROUP BY state;",
 'cleanup_tasks':"SELECT state,COUNT(*) FROM xiaozhi_esp32_server.ai_identity_cleanup GROUP BY state;",
 'storage_hours':"SELECT hour,state,COUNT(*),SUM(fact_count) FROM one_api.memory_storage_hours GROUP BY hour,state ORDER BY hour DESC LIMIT 12;",
 'memory_charge_states':"SELECT operation,state,COUNT(*) FROM one_api.memory_charges GROUP BY operation,state;",
 'retired_entity_backlog':"SELECT COUNT(*) FROM one_api.memory_entities WHERE state='retired' AND cleanup_confirmed=TRUE;",
 'portrait_rows':"SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_person_memory_entity WHERE portrait_written=TRUE;",
 'overdue_tasks':"SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_memory_task WHERE state IN('pending','retry','accepted','review','submitting') AND created_at<DATE_SUB(NOW(),INTERVAL 1 DAY);",
 'daily_windows':"SELECT COUNT(*),MAX(daily_started_at) FROM xiaozhi_esp32_server.ai_person_memory_entity;"
}
report['counts']={name:sql(query) for name,query in queries.items()}
report['healthy']=all(report['services'].get(name)=='online' for name in ['manager-api','manager-web','xiaozhi-server','voiceprint-api']) and all(value==200 for value in report['http'].values())
with (release/'observations.jsonl').open('a') as output:output.write(json.dumps(report,ensure_ascii=False)+'\n')
print(json.dumps(report,ensure_ascii=False),flush=True)
