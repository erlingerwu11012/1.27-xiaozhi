from pathlib import Path
import hashlib
import json
import subprocess

STAGE=Path(__file__).parent
HOST='root@121.40.239.140'
REMOTE='/root/prjs/tmp/tts-spine-sync-20261013'
def call(args):subprocess.run(args,check=True)
FILES=['core/connection.py','core/providers/tools/device_mcp/mcp_handler.py']
before={f:hashlib.sha256((STAGE/'baseline/server'/f).read_bytes()).hexdigest() for f in FILES}
(STAGE/'before-hashes.json').write_text(json.dumps(before),encoding='utf-8')
call(['ssh','-o','BatchMode=yes',HOST,'mkdir -p '+REMOTE+'/server/core/providers/tools/device_mcp'])
for f in FILES:call(['scp','-q',str(STAGE/'server'/f),HOST+':'+REMOTE+'/server/'+f])
for f in ('deploy_server.py','test_server_touch.py','before-hashes.json'):
    call(['scp','-q',str(STAGE/f),HOST+':'+REMOTE+'/'+f])
print('Uploaded candidate and tests; production unchanged',flush=True)
