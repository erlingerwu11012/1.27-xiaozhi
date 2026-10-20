from pathlib import Path
import json,time,pymysql
S=Path('/root/prjs/tmp/quiet-maintenance-20261018')
password=json.loads(Path('/root/prjs/tmp/hardware-followup-20261013/private-test-env.json').read_text())['PERSON_MEMORY_TEST_PASSWORD']
deadline=time.monotonic()+180;prior=None
while time.monotonic()<deadline:
 with pymysql.connect(host='127.0.0.1',user='root',password=password,database='xiaozhi_esp32_server',cursorclass=pymysql.cursors.DictCursor) as db:
  with db.cursor() as c:
   c.execute('SELECT id,state,watermark,attempts,last_error,next_attempt_at FROM ai_memory_task WHERE id=%s',('usr_6f9a8c4699244ec8b2dc2d9204c08ebc',));row=c.fetchone()
 if row['state']!=prior:print(json.dumps(row,default=str),flush=True);prior=row['state']
 (S/'memory-final-state.json').write_text(json.dumps(row,default=str,indent=2))
 if row['state'] in ['complete','failed','cancelled','review','retry']:break
 time.sleep(10)
