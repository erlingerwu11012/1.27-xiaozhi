"""Read-only counts for the requested account's first voiceprint transition."""
from pathlib import Path
import json
import subprocess

target = json.loads((Path("/root/prjs/tmp/memory-test-20260930") / "target.json").read_text())
account = int(target["account_id"])
mysql = ["docker", "exec", "-i", "xiaozhi-esp32-server-db", "sh", "-c",
         'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(query):
    return subprocess.run(mysql, input=query, text=True, capture_output=True, check=True).stdout.strip()

state = sql("SELECT JSON_OBJECT('mode',mode,'generation',default_generation,'directory_version',directory_version) FROM xiaozhi_esp32_server.ai_account_identity_state WHERE account_id=%d;" % account)
voices = sql("SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_agent_voice_print WHERE creator=%d AND binding_state='ready' AND vector_id IS NOT NULL;" % account)
members = sql("SELECT COUNT(*) FROM xiaozhi_esp32_server.ai_user_identity WHERE account_id=%d AND kind='member' AND status='active';" % account)
cleanups = sql("SELECT JSON_OBJECT('state',state,'cloud_done',cloud_done,'portrait_done',portrait_done,'local_done',local_done) FROM xiaozhi_esp32_server.ai_identity_cleanup WHERE account_id=%d ORDER BY created_at DESC LIMIT 5;" % account)
entities = sql("SELECT state,COUNT(*) FROM xiaozhi_esp32_server.ai_person_memory_entity WHERE account_id=%d GROUP BY state;" % account)
print(json.dumps({"state": json.loads(state), "ready_voiceprint_count": int(voices),
                  "active_member_count": int(members),
                  "cleanup_states": [json.loads(line) for line in cleanups.splitlines() if line],
                  "memory_entity_states": entities}, ensure_ascii=False))
