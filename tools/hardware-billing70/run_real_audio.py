"""Authorized synthetic audio, actual production channel; no customer wallet."""
from pathlib import Path
import subprocess, json, os
root=Path('/root/prjs/tmp/hardware-billing70-20261001')
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
raw=subprocess.run(mysql,input='SELECT `key`,base_url FROM one_api.channels WHERE id=7 AND type=17 AND status=1;',capture_output=True,text=True,check=True).stdout.strip()
key,base=raw.split('\t')
env=dict(os.environ,PATH='/usr/local/go/bin:'+os.environ['PATH'],CLOUD_HW_AUDIO_KEY=key,CLOUD_HW_AUDIO_BASE=base,CLOUD_HW_AUTHORIZED='1',HW_AUDIO_REPORT=str(root/'tests/real-production-audio-ledger.json'))
with (root/'tests/real-production-audio-ledger.log').open('w') as f:
    result=subprocess.run(['go','test','-tags','cloud_hardware_audio','./bailian','-run','TestHardwareAudioRealCloudAndLedger','-count=1','-v'],cwd=root/'candidate/gateway',env=env,stdout=f,stderr=subprocess.STDOUT)
print(json.dumps({'production_channel_audio_exit':result.returncode}))
if result.returncode:
    for line in (root/'tests/real-production-audio-ledger.log').read_text().splitlines():
        if 'hardware_audio_cloud_test.go:' in line or 'isolated settlement error:' in line:print(line[:250])
raise SystemExit(result.returncode)
