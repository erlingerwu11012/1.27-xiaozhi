import importlib.util,json,re
import pymysql
spec=importlib.util.spec_from_file_location('private_db','/root/prjs/xiaozhi_mcp_gateway/core/db_config.py');cfg=importlib.util.module_from_spec(spec);spec.loader.exec_module(cfg)
db=pymysql.connect(host=cfg.DB_HOST,port=cfg.DB_PORT,user=cfg.DB_USER,password=cfg.DB_PASSWORD,database=cfg.DB_NAME,charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor)
with db.cursor() as c:
 c.execute('START TRANSACTION READ ONLY')
 for table in ['ai_person_material','ai_agent_chat_history']:
  c.execute('SHOW TABLES LIKE %s',(table,))
  if not c.fetchone():continue
  c.execute('SHOW COLUMNS FROM `'+table+'`');cols=[x['Field'] for x in c.fetchall()];print('COLUMNS',table,cols)
  textcols=[x for x in cols if any(v in x for v in ['content','payload','text','metadata'])]
  clock=next((x for x in ['created_at','create_date','created_time'] if x in cols),None)
  if not textcols or not clock:continue
  fields=','.join('`'+x+'`' for x in [clock]+textcols)
  c.execute('SELECT '+fields+' FROM `'+table+'` WHERE `'+clock+'` BETWEEN %s AND %s ORDER BY `'+clock+'` DESC LIMIT 200',('2026-10-09 01:25:00','2026-10-09 01:35:00'))
  rows=c.fetchall();hits=0
  for row in rows:
   text=' '.join(str(row.get(x,'')) for x in textcols)
   if not any(x in text for x in ['self_camera_take_photo','self.camera.take_photo','vision_not_ready','视觉服务']):continue
   codes=set(re.findall(r'(?:vision_[a-z_0-9]+|capture_failed|camera_busy|camera_not_ready|session_mismatch|unclassified_tool_error|device_failure)',text))
   hits+=1;print('CAMERA_ERROR_METADATA',str(row[clock]),sorted(codes))
  print('SCANNED',table,len(rows),'camera_records',hits)
db.rollback();db.close()

