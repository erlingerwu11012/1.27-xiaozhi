"""Read-only voiceprint configuration metadata; never print endpoint credentials."""
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from urllib.error import HTTPError, URLError
import json
import subprocess
import urllib.request

target = json.loads((Path("/root/prjs/tmp/memory-test-20260930") / "target.json").read_text())
mysql = ["docker", "exec", "-i", "xiaozhi-esp32-server-db", "sh", "-c",
         'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
secret = subprocess.run(mysql, input="SELECT param_value FROM xiaozhi_esp32_server.sys_params WHERE param_code='server.secret';",
                        text=True, capture_output=True, check=True).stdout.strip()
body = json.dumps({"macAddress": target["device_id"], "clientId": "diagnostic-read-only",
                   "selectedModule": {}}, ensure_ascii=False).encode()
request = urllib.request.Request("http://127.0.0.1:8002/xiaozhi/config/agent-models", data=body,
    headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(request, timeout=8) as response:
    result = json.loads(response.read())
config = result.get("data") or {}
voice = config.get("voiceprint") or {}
url = urlsplit(voice.get("url") or "")
health = "not_checked"
if url.scheme in ("http", "https") and url.netloc and parse_qs(url.query).get("key", [""])[0]:
    health_url = "%s://%s/voiceprint/health?key=%s" % (
        url.scheme, url.netloc, parse_qs(url.query)["key"][0])
    try:
        with urllib.request.urlopen(health_url, timeout=4) as response:
            value = json.loads(response.read())
            health = "healthy" if response.status == 200 and value.get("status") == "healthy" else "not_healthy"
    except (HTTPError, URLError, TimeoutError) as exc:
        health = type(exc).__name__
print(json.dumps({"api_code": result.get("code"), "voiceprint_config_present": bool(voice),
                  "account_matches_device": str(config.get("sys_user_id") or "") == str(target["account_id"]),
                  "agent_matches_device": str(config.get("agent_id") or "") == str(target["agent_id"]),
                  "voiceprint_url_present": bool(url.scheme and url.netloc),
                  "voiceprint_key_present": bool(parse_qs(url.query).get("key", [""])[0]),
                  "voiceprint_service_health": health,
                  "speaker_profile_count": len(voice.get("speaker_profiles") or []),
                  "current_identity_mode": target["state"]["mode"],
                  "current_bound_member_count": len(target.get("voice_members") or [])},
                 ensure_ascii=False))
