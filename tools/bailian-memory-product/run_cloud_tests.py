"""SSH-host opt-in real cloud tests; synthetic wallets, no customer memories."""
import json
import os
import shlex
import subprocess
from pathlib import Path

root = Path("/root/prjs/tmp/one-api-bailian-memory-product")
config = {}
for line in Path("/etc/one-api-bailian.env").read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        pieces = shlex.split(value)
        config[key.strip()] = pieces[0] if pieces else ""
channel = int(config["BAILIAN_MEMORY_CHANNEL_ID"])
query = "SELECT `key` FROM one_api.channels WHERE id=" + str(channel) + " AND type=17 AND status=1 LIMIT 1;"
response = subprocess.run(["docker", "exec", "-i", "xiaozhi-esp32-server-db", "sh", "-c",
    'exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names'],
    input=query, text=True, capture_output=True, check=True)
upstream = response.stdout.strip()
assert upstream and "\n" not in upstream
environment = dict(os.environ, GOPROXY="off", CLOUD_MEMORY_TEST_KEY=upstream,
    CLOUD_MEMORY_TEST_AUTHORIZED="1", BAILIAN_MEMORY_LIBRARY_ID=config.get("BAILIAN_MEMORY_LIBRARY_ID", ""))
log = Path("/tmp/bailian-memory-real-cloud.log")
with log.open("w") as output:
    result = subprocess.run(["/usr/local/go/bin/go", "test", "-tags", "cloud_memory", "./bailian",
        "-run", "TestMemoryRealCloudLifecycle", "-count=1", "-v"], cwd=root,
        env=environment, stdout=output, stderr=subprocess.STDOUT)
print(json.dumps({"cloud_exit": result.returncode}), flush=True)
print(log.read_text(errors="replace")[-4000:], flush=True)
raise SystemExit(result.returncode)
