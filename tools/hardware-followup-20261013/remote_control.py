"""Run scoped orchestration scripts using the server's existing Python runtime."""
import base64, shlex, subprocess, sys
from pathlib import Path
def run(code):
    encoded=base64.b64encode(code.encode()).decode()
    bootstrap="import base64;exec(compile(base64.b64decode("+repr(encoded)+"),'<followup-orchestrator>','exec'))"
    return subprocess.run(['ssh','root@121.40.239.140','/root/miniconda3/envs/xiaozhi-esp32-server/bin/python -c '+shlex.quote(bootstrap)]).returncode
if __name__=='__main__':
    raise SystemExit(run(Path(sys.argv[1]).read_text(encoding='utf-8')))
