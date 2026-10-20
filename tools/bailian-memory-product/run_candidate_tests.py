"""SSH-host candidate tests. No production process or business row is changed."""
import json
import os
import subprocess
from pathlib import Path

candidate = Path("/root/prjs/tmp/bailian-memory-product")


def run(command, directory, log, environment=None):
    with open(log, "w") as output:
        result = subprocess.run(command, cwd=directory, env=environment, stdout=output, stderr=subprocess.STDOUT)
    print(json.dumps({"command":command, "exit_code":result.returncode, "log":log}), flush=True)
    if result.returncode:
        print(Path(log).read_text(errors="replace")[-8000:], flush=True)
    return result.returncode


subprocess.run(["python3", "/tmp/migration_fixture.py"], check=True)
database = json.loads(Path("/tmp/bailian-memory-migration-result.json").read_text())["database"]
assert database.startswith("bailian_memory_test_")
password = subprocess.run(["docker","exec","xiaozhi-esp32-server-db","sh","-c",'printf "%s" "$MYSQL_ROOT_PASSWORD"'], capture_output=True, text=True, check=True).stdout
environment = dict(os.environ, PERSON_MEMORY_TEST_DATABASE=database, PERSON_MEMORY_TEST_PASSWORD=password)
status = run(["mvn","-o","test"], candidate/"main/manager-api", "/tmp/bailian-memory-all-java-tests.log", environment)
python = "/root/miniconda3/envs/xiaozhi-esp32-server/bin/python"
status |= run([python,"-m","unittest","discover","-s","test","-p","test_person_memory*.py","-v"],candidate/"main/xiaozhi-server","/tmp/bailian-memory-python-tests.log")
status |= run(["/usr/local/go/bin/go","test","./bailian","./model","./cmd/bailian"],Path("/root/prjs/tmp/one-api-bailian-memory-product"),"/tmp/bailian-memory-all-go-tests.log",dict(os.environ,GOPROXY="off"))
print(json.dumps({"status":status,"test_database":database}), flush=True)
raise SystemExit(status)
