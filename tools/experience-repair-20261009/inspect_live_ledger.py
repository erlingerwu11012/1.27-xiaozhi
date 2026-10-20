import sqlite3,json
p='/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/data/harness/operations.sqlite3'
with sqlite3.connect('file:'+p+'?mode=ro',uri=True) as db:
 print(json.dumps({'columns':db.execute('PRAGMA table_info(dispatch)').fetchall(),'tables':db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}))
