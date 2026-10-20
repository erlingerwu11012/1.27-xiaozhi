import sqlite3,json,subprocess,re,pymysql
from pathlib import Path
S=Path(__file__).parent
meta=json.loads(subprocess.check_output(['docker','inspect','one-api']))[0]
env=dict(x.split('=',1) for x in meta['Config']['Env'] if '=' in x)
dsn=env.get('SQL_DSN','')
auth,_,tail=dsn.rpartition('@tcp(');host,_,tail=tail.partition(')/');user,_,password=auth.partition(':');hostname,_,port=host.partition(':');db=tail.split('?')[0]
assert user and hostname and db
d=pymysql.connect(host=hostname,port=int(port or 3306),user=user,password=password,database=db,cursorclass=pymysql.cursors.DictCursor)
cur=d.cursor();cur.execute('SHOW COLUMNS FROM channels');columns={r['Field'] for r in cur.fetchall()}
wanted=[n for n in ['id','name','status','type','models','model_mapping'] if n in columns]
cur.execute('SELECT '+','.join(wanted)+' FROM channels');rows=[dict(r) for r in cur.fetchall() if any(m in str(r['models']) for m in ('qwen3-vl-flash','qwen3.7-plus','Qwen3-VL'))]
print(json.dumps(rows,ensure_ascii=False));(S/'oneapi-vision-channel.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
d.close()
