from pathlib import Path
import json,sys,pymysql
s=Path('/root/prjs/tmp/hardware-followup-20261013');sys.path.insert(0,str(s));from budget import Budget
print('budget',Budget().report())
rows=[json.loads(x) for x in (s/'final07-results.jsonl').read_text().splitlines()]
print('rows',len(rows),'failures',[{k:r[k] for k in ['group','turn','errors','speech']} for r in rows if r['errors']]);print('recent',[(r['group'],r['turn'],r.get('speech')) for r in rows[-6:]])
e=json.loads((s/'private-test-env.json').read_text());db=pymysql.connect(host='127.0.0.1',user='root',password=e['PERSON_MEMORY_TEST_PASSWORD'],database='bailian_memory_test_restore_followup20261013')
with db.cursor() as c:c.execute('SHOW COLUMNS FROM ai_memory_override');print('columns',[r[0] for r in c.fetchall()])
