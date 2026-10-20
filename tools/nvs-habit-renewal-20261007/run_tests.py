import json,os,re,subprocess,sys
from pathlib import Path
stage=Path(__file__).parent
root=stage/'work/xiaozhi-server'
env=os.environ.copy();env['TEST_ROOT']=str(root)
names=['habit_sync','habit_sync_api','interaction_renewal','reminder_reliability','operation_control','operation_pipeline','unified_recipient_outbound','reminder_interaction','reminder_voice','reminder_voice_abort','reminder_voice_download','device_send_auth','qwen_audio_tts_plus','recipient_resolver','device_reminder']
results=[]
for name in names:
 r=subprocess.run([sys.executable,'/root/prjs/tmp/reminder-reliability-fix-20261007/offline_test.py',name],cwd=root,env=env,capture_output=True,text=True,timeout=100)
 log=r.stdout+r.stderr;(stage/('test-'+name+'.log')).write_text(log)
 count=re.search(r'Ran (\d+) tests?',log)
 row={'suite':name,'passed':r.returncode==0 and '[FAIL]' not in log,'tests':int(count[1]) if count else log.count('[PASS]')};results.append(row);print(json.dumps(row),flush=True)
 if not row['passed']:print(log[-5000:],flush=True)
(stage/'test-results.json').write_text(json.dumps(results,indent=2))
sys.exit(0 if all(x['passed'] for x in results) else 1)
