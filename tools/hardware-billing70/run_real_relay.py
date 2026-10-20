"""Authorized isolated real Ali tests; credentials stay in server process memory."""
from pathlib import Path
import subprocess,json,os
root=Path('/root/prjs/tmp/hardware-billing70-20261001')
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(q):return subprocess.run(mysql,input=q,text=True,capture_output=True,check=True).stdout.strip()
key=sql('SELECT `key` FROM one_api.channels WHERE id=2 AND type=17 AND status=1;')
v=json.loads(sql("SELECT config_json FROM xiaozhi_esp32_server.ai_model_config WHERE id='VLLM_QwenVLVLLM' AND model_type='VLLM';"))
env=dict(os.environ,PATH='/usr/local/go/bin:'+os.environ['PATH'],GOPROXY='https://goproxy.cn',CLOUD_HW_TEST_KEY=key,CLOUD_HW_VISION_KEY=v['api_key'],CLOUD_HW_AUTHORIZED='1',CLOUD_HW_RESULT_FILE=str(root/'tests/real-auth-relay-ledger.json'))
with (root/'tests/real-auth-relay-ledger.log').open('w') as f:r=subprocess.run(['go','test','-tags','cloud_hardware','./relay/controller','-run','TestHardwareRealAliRelayAndPaidLedger','-count=1','-v'],env=env,cwd=root/'candidate/gateway',stdout=f,stderr=subprocess.STDOUT)
print(json.dumps({'real_auth_relay_exit':r.returncode}))
raise SystemExit(r.returncode)
