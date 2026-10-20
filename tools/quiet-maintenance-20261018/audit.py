from pathlib import Path
import json, pymysql, yaml, requests, sqlite3
ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
account='2022326478036516866'
password=json.loads(Path('/root/prjs/tmp/hardware-followup-20261013/private-test-env.json').read_text())['PERSON_MEMORY_TEST_PASSWORD']
db=pymysql.connect(host='127.0.0.1',user='root',password=password,database='xiaozhi_esp32_server',cursorclass=pymysql.cursors.DictCursor)
with db.cursor() as c:
    for name,sql,args in [
        ('agent','SELECT id,mem_model_id FROM ai_agent WHERE id=%s',('57a71787c86f4f158c90a5c6c6e7016b',)),
        ('tables',"SHOW TABLES LIKE 'ai_person%'",()),
        ('behavior_state','SELECT * FROM ai_person_behavior_analysis WHERE account_id=%s',(account,)),
        ('behavior_counts','SELECT user_id,generation,COUNT(*) n,MIN(id) first_id,MAX(id) last_id,MIN(FROM_UNIXTIME(occurred_at)) first_at,MAX(FROM_UNIXTIME(occurred_at)) last_at FROM ai_person_behavior_event WHERE account_id=%s GROUP BY user_id,generation',(account,)),
        ('memory_entities','SELECT * FROM ai_person_memory_entity WHERE account_id=%s',(account,)),
        ('memory_tasks','SELECT id,user_id,generation,kind,state,watermark,attempts,last_error,created_at FROM ai_memory_task WHERE account_id=%s ORDER BY created_at DESC LIMIT 10',(account,)),
        ('material_counts','SELECT user_id,kind,COUNT(*) n,MAX(id) last_id FROM ai_person_material WHERE account_id=%s GROUP BY user_id,kind',(account,)),
    ]:
        try:c.execute(sql,args);print(name,json.dumps(c.fetchall(),default=str,ensure_ascii=False))
        except Exception as e:print(name,type(e).__name__)
secret=yaml.safe_load((ROOT/'data/.config.yaml').read_text())['manager-api']['secret']
r=requests.get('http://127.0.0.1:18005/xiaozhi/user-identities/internal/state/'+account,headers={'Authorization':'Bearer '+secret},timeout=5)
state=r.json().get('data',{})
print('directory',json.dumps(state,ensure_ascii=False))
for file in (ROOT/'data').rglob('*.sqlite3'):
    with sqlite3.connect('file:'+str(file)+'?mode=ro',uri=True) as s:
        names=[x[0] for x in s.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        print('sqlite',str(file.relative_to(ROOT)),names)
        if 'material' in names:print('outbox',s.execute('SELECT kind,COUNT(*) FROM material WHERE account=? GROUP BY kind',(account,)).fetchall())
