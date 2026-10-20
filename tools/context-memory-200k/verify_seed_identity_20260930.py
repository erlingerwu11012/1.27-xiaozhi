"""Read-only identity comparison; never print person IDs or memory text."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path("/root/prjs/tmp/memory-test-20260930")
target = json.loads((root / "target.json").read_text())
seed = json.loads((root / "seed-result.json").read_text())
state = target["state"]
account = str(target["account_id"])
person = state.get("default_user_id") or ""
generation = str(state.get("default_generation") or 0)
owner = str(seed["owner_private"])
derived = "re_" + hashlib.sha256(":".join((owner, account, person, generation)).encode()).hexdigest()[:60]
mysql = ["docker", "exec", "-i", "xiaozhi-esp32-server-db", "sh", "-c",
         'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
query = """SELECT JSON_OBJECT('active',SUM(state='active'),'retired',SUM(state='retired'))
FROM xiaozhi_esp32_server.ai_person_memory_entity
WHERE account_id=%s AND user_id=CONVERT(X'%s' USING utf8mb4) AND generation=%s;""" % (
    account, person.encode().hex(), generation)
raw = subprocess.run(mysql, input=query, capture_output=True, text=True, check=True).stdout.strip()
entity = json.loads(raw) if raw else {}
charge_query = """SELECT COUNT(*) FROM one_api.memory_charges
WHERE BINARY cloud_user_id=BINARY CONVERT(X'%s' USING utf8mb4)
  AND operation='search' AND created_at>=UNIX_TIMESTAMP('2026-09-30 01:33:00')
  AND created_at<UNIX_TIMESTAMP('2026-09-30 01:36:00');""" % derived.encode().hex()
charges = subprocess.run(mysql, input=charge_query, capture_output=True, text=True, check=True).stdout.strip()
print(json.dumps({"device_matches_test": target["device_id"] == seed["device"],
                  "current_mode": state["mode"],
                  "test_cloud_identity_matches_current_default": derived == seed["cloud_private"],
                  "active_entity_count": entity.get("active"),
                  "retired_entity_count": entity.get("retired"),
                  "cloud_search_calls_in_device_window": int(charges or 0),
                  "fact_count_at_test_end": seed.get("fact_count"),
                  "test_state": seed.get("state")}, ensure_ascii=False))
