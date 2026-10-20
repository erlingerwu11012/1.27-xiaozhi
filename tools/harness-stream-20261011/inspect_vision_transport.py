import json,subprocess,pymysql,requests
from urllib.parse import urlparse
m=json.loads(subprocess.check_output(['docker','inspect','one-api']))[0]
e=dict(x.split('=',1) for x in m['Config']['Env'] if '=' in x)
a,_,t=e['SQL_DSN'].rpartition('@tcp(');h,_,t=t.partition(')/');u,_,p=a.partition(':');host,_,port=h.partition(':')
with pymysql.connect(host=host,port=int(port or 3306),user=u,password=p,database=t.split('?')[0],cursorclass=pymysql.cursors.DictCursor) as d:
 with d.cursor() as c:
  c.execute('SELECT id,type,base_url,`key`,model_mapping FROM channels WHERE id IN (8,9,11)');rows=c.fetchall()
  main_key=rows[0]['key']
  for r in rows:
   key=r.pop('key');url=urlparse(r.pop('base_url') or '')
   r.update(base_host=url.hostname,base_path=url.path,key_present=bool(key),same_main_key=key==main_key)
   print(json.dumps(r))
   if r['id']==9:
    response=requests.get('https://dashscope.aliyuncs.com/compatible-mode/v1/models',headers={'Authorization':'Bearer '+key},timeout=20)
    body=response.json()
    print(json.dumps({'upstream_list_status':response.status_code,'vision_models':[x.get('id') for x in body.get('data',[]) if 'vl' in x.get('id','').lower()],'error_code':body.get('error',{}).get('code')}))
