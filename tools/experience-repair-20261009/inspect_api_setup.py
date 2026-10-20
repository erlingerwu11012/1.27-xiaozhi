import importlib.util,json,subprocess,os,secrets,sys
from pathlib import Path
S=Path(__file__).parent
sys.path.insert(0,str(S));import bootstrap
for n in ('self_get_system_info','self_screen_get_render_status','self_camera_identify_person','camera_face_enroll_status'):
 d=json.load(open('/root/prjs/tmp/harness-20261007/pack.json'));print(n,d['fixtures'].get(n))
# Prepare only the dedicated test database and an isolated redis instance.
env=json.loads((S/'private-test-env.json').read_text())
import pymysql
c=pymysql.connect(host='127.0.0.1',user='root',password=env['PERSON_MEMORY_TEST_PASSWORD'],database=env['PERSON_MEMORY_TEST_DATABASE'],autocommit=True)
with c.cursor() as q:
 q.execute('SHOW COLUMNS FROM sys_params');print('sys_params_columns',[x[0] for x in q.fetchall()])
print('java_reports')
import xml.etree.ElementTree as ET
for p in (S/'manager-api/target/surefire-reports').glob('TEST-*.xml'):
 r=ET.parse(p).getroot();print(p.name,{k:r.get(k) for k in ['tests','failures','errors','skipped']})
