from pathlib import Path
import json,pymysql
S=Path('/root/prjs/tmp/quiet-maintenance-20261018')
p=json.loads(Path('/root/prjs/tmp/hardware-followup-20261013/private-test-env.json').read_text())['PERSON_MEMORY_TEST_PASSWORD']
with pymysql.connect(host='127.0.0.1',user='root',password=p,database='xiaozhi_esp32_server',cursorclass=pymysql.cursors.DictCursor) as db:
 with db.cursor() as c:
  queries={
   'behavior_state':'SELECT * FROM ai_person_behavior_analysis WHERE account_id=%s',
   'behavior_counts':'SELECT user_id,COUNT(*) n,MIN(FROM_UNIXTIME(occurred_at)) first_at,MAX(FROM_UNIXTIME(occurred_at)) last_at FROM ai_person_behavior_event WHERE account_id=%s GROUP BY user_id',
   'memory_entity':'SELECT processed_watermark,daily_watermark,daily_started_at,state FROM ai_person_memory_entity WHERE account_id=%s',
   'overrides':'SELECT id,action,state,created_at FROM ai_memory_override WHERE account_id=%s',
   'tasks':'SELECT id,state,watermark,attempts,last_error,next_attempt_at FROM ai_memory_task WHERE account_id=%s ORDER BY created_at DESC LIMIT 5',
   'open_turns':"SELECT m.id,m.turn_id,m.kind,m.created_at FROM ai_person_material m WHERE m.account_id=%s AND m.kind='dialogue' AND NOT EXISTS(SELECT 1 FROM ai_person_material z WHERE z.account_id=m.account_id AND z.user_id=m.user_id AND z.generation=m.generation AND z.turn_id=m.turn_id AND z.kind='dialogue_end') ORDER BY m.id",
   'source_counts':"SELECT MIN(id) first_id,MAX(id) last_id,COUNT(*) rows_n,SUM(user_tokens) tokens FROM ai_person_material WHERE account_id=%s AND recall_allowed=TRUE",
  }
  result={}
  for name,sql in queries.items():c.execute(sql,('2022326478036516866',));result[name]=c.fetchall()
(S/'result-state.json').write_text(json.dumps(result,default=str,ensure_ascii=False,indent=2));print(json.dumps(result,default=str,ensure_ascii=False))
