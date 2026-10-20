import importlib.util,json
from pathlib import Path
import pymysql
spec=importlib.util.spec_from_file_location('private_db','/root/prjs/xiaozhi_mcp_gateway/core/db_config.py')
cfg=importlib.util.module_from_spec(spec);spec.loader.exec_module(cfg)
db=pymysql.connect(host=cfg.DB_HOST,port=cfg.DB_PORT,user=cfg.DB_USER,password=cfg.DB_PASSWORD,database=cfg.DB_NAME,cursorclass=pymysql.cursors.DictCursor)
with db.cursor() as c:
    c.execute('SELECT sync_state,COUNT(*) AS count FROM sys_habits GROUP BY sync_state');states=c.fetchall()
    c.execute("SELECT COUNT(*) AS count FROM sys_habits WHERE source='integration_test'");test_habits=c.fetchone()['count']
    c.execute("SELECT COUNT(*) AS count FROM ai_device WHERE alias='临时软件协议验收'");test_devices=c.fetchone()['count']
assert test_habits==0 and test_devices==0
result={'habit_states':states,'test_habits_remaining':test_habits,'test_devices_remaining':test_devices}
Path(__file__).with_name('final-status.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result));db.close()
