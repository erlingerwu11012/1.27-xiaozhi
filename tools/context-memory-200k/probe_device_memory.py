"""Read-only metadata for the explicitly requested device; never prints secrets."""
from pathlib import Path
import json,subprocess,sys,os,time,sqlite3

device=sys.argv[1].lower();assert len(device)==17 and all(c in '0123456789abcdef:' for c in device)
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(q):return subprocess.run(mysql,input=q,text=True,capture_output=True,check=True).stdout.strip()
def one(q):
    value=sql(q);return json.loads(value) if value else None
out=Path('/root/prjs/tmp/memory-test-20260930');out.mkdir(exist_ok=True);os.chmod(out,0o700)
target=one("SELECT JSON_OBJECT('device_id',d.mac_address,'account_id',d.user_id,'agent_id',d.agent_id,'memory',a.mem_model_id) FROM xiaozhi_esp32_server.ai_device d JOIN xiaozhi_esp32_server.ai_agent a ON a.id=d.agent_id AND a.user_id=d.user_id WHERE LOWER(d.mac_address)='"+device+"';")
assert target,'device_not_found'
account=int(target['account_id']);agent=target['agent_id'];assert agent.isalnum() or all(c.isalnum() or c in '_-' for c in agent)
state=one("SELECT JSON_OBJECT('mode',mode,'default_user_id',default_user_id,'default_generation',default_generation,'directory_version',directory_version) FROM xiaozhi_esp32_server.ai_account_identity_state WHERE account_id="+str(account)+";")
target['state']=state
members=sql("SELECT JSON_OBJECT('person_id',u.user_id,'display_name',u.display_name,'voiceprint_id',v.id,'template_version',v.template_version) FROM xiaozhi_esp32_server.ai_agent_voice_print v JOIN xiaozhi_esp32_server.ai_user_identity u ON u.account_id=v.creator AND u.user_id=v.user_id WHERE v.creator="+str(account)+" AND v.binding_state='ready' AND v.vector_id IS NOT NULL AND u.kind='member' AND u.status='active';")
target['voice_members']=[json.loads(row) for row in members.splitlines() if row]
target['material_counts']=sql("SELECT kind,COUNT(*),SUM(CHAR_LENGTH(content)) FROM xiaozhi_esp32_server.ai_person_material WHERE account_id="+str(account)+" AND agent_id='"+agent+"' GROUP BY kind;")
target['entity_states']=sql("SELECT state,COUNT(*),SUM(daily_watermark>processed_watermark) FROM xiaozhi_esp32_server.ai_person_memory_entity WHERE account_id="+str(account)+" GROUP BY state;")
target['task_states']=sql("SELECT state,COUNT(*) FROM xiaozhi_esp32_server.ai_memory_task WHERE account_id="+str(account)+" GROUP BY state;")
target['archives']=sql("SELECT identity_status,COUNT(*),SUM(recall_allowed) FROM xiaozhi_esp32_server.ai_agent_chat_history WHERE account_id="+str(account)+" AND agent_id='"+agent+"' GROUP BY identity_status;")
target['existing_overrides']=sql("SELECT state,COUNT(*) FROM xiaozhi_esp32_server.ai_memory_override WHERE account_id="+str(account)+" GROUP BY state;")
target['at']=time.strftime('%Y-%m-%d %H:%M:%S %z')
(out/'target.json').write_text(json.dumps(target,ensure_ascii=False,indent=2));os.chmod(out/'target.json',0o600)
pm=json.loads(subprocess.run(['pm2','jlist'],capture_output=True,text=True,check=True).stdout)
manager=next(p for p in pm if p['name']=='manager-api')
environment=dict(x.decode().split('=',1) for x in Path('/proc/'+str(manager['pid'])+'/environ').read_bytes().split(b'\0') if b'=' in x)
result={k:target[k] for k in ('at','device_id','memory','material_counts','entity_states','task_states','archives','existing_overrides')}
result['identity_mode']=state['mode'] if state else 'not_initialized'
result['bound_voice_members']=[m['display_name'] for m in target['voice_members']]
result['service_flags']={'memory_enabled':environment.get('MEMORY_PRODUCT_ENABLED'),'portrait_enabled':environment.get('MEMORY_PORTRAIT_ENABLED')}
result['pm2']={p['name']:p['pm2_env']['status'] for p in pm if p['name'] in ('manager-api','xiaozhi-server','manager-web','voiceprint-api')}
local=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/data/person-material-outbox.sqlite3')
if local.exists():
    with sqlite3.connect('file:'+str(local)+'?mode=ro',uri=True) as db:
        result['outbox_counts']=db.execute('SELECT kind,COUNT(*) FROM material WHERE account=? GROUP BY kind',(str(account),)).fetchall()
print(json.dumps(result,ensure_ascii=False))
