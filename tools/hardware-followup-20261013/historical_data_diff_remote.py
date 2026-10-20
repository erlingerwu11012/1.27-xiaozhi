from pathlib import Path
import json,hashlib,re,os,datetime
import pymysql,requests,yaml
S=Path('/root/prjs/tmp/hardware-followup-20261013');ROOT=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
old_manifest=json.loads(Path('/root/prjs/tmp/harness-stream-20261011/predeploy-backup02/manifest.json').read_text());new_manifest=json.loads((S/'predeploy-backup02/manifest.json').read_text())
old_db=old_manifest['restore_database'];new_db=new_manifest['restore_database'];assert all(re.fullmatch('bailian_memory_test_restore_[A-Za-z0-9_]+',x) for x in [old_db,new_db])
pw=json.loads((S/'private-test-env.json').read_text())['PERSON_MEMORY_TEST_PASSWORD'];secret=yaml.safe_load((ROOT/'data/.config.yaml').read_text())['manager-api']['secret']
cfg=requests.post('http://127.0.0.1:18005/xiaozhi/config/agent-models',headers={'Authorization':'Bearer '+secret},json={'macAddress':'ac:a7:04:fd:20:2c','clientId':'followup-readonly-data-diff','selectedModule':{}},timeout=8).json();assert cfg['code']==0
data=cfg['data'];llm=data['LLM'][data['selected_module']['LLM']];account=str(llm['hardware_account_id']);assert account.isdigit() and account!='99003'
db=pymysql.connect(host='127.0.0.1',user='root',password=pw,cursorclass=pymysql.cursors.DictCursor)
private={'before_database':old_db,'after_database':new_db,'account_id':account,'before_backup_created':old_manifest['created'],'after_backup_created':new_manifest['created'],'tables':{}}
summary={'mode':'read_only_backup_diff','before_backup_created':old_manifest['created'],'after_backup_created':new_manifest['created'],'production_writes':0,'automatically_restored_rows':0,'tables':{},'limits':['Changes span normal user operations and the reported fault window; row differences alone do not prove misdeletion.','Original user chat and archived instructions are not automatically classified as corrupted facts.','No current personal records or override markers were edited.']}
for table in ['ai_person_material','ai_memory_override','ai_agent_chat_history']:
 def read(schema):
  with db.cursor() as c:c.execute('SELECT * FROM `'+schema+'`.`'+table+'` WHERE account_id=%s',(account,));return {str(r['id']):r for r in c.fetchall()}
 before=read(old_db);after=read(new_db);removed=sorted(before.keys()-after.keys());added=sorted(after.keys()-before.keys());common=before.keys()&after.keys()
 changed=[k for k in common if any(before[k][field]!=after[k][field] for field in before[k].keys()&after[k].keys())]
 field_changes={}
 for k in changed:
  for field in before[k].keys()&after[k].keys():
   if before[k][field]!=after[k][field]:field_changes[field]=field_changes.get(field,0)+1
 private['tables'][table]={'before_count':len(before),'after_count':len(after),'removed':[before[k] for k in removed],'added':[after[k] for k in added],'changed':[{'before':before[k],'after':after[k]} for k in changed]}
 summary['tables'][table]={'before_count':len(before),'after_count':len(after),'removed_ids':removed,'added_count':len(added),'changed_ids':changed,'changed_fields_counts':field_changes,'schema_added_fields':sorted(set(next(iter(after.values()),{}))-set(next(iter(before.values()),{})))}
 if table=='ai_memory_override':
  summary['current_wildcard_markers']=[{'id':r['id'],'action':r.get('action'),'state':r.get('state'),'created_at':str(r.get('created_at')),'material_cutoff_id':r.get('material_cutoff_id'),'archive_cutoff_id':r.get('archive_cutoff_id')} for r in after.values() if r.get('match_text')=='*']
 if table=='ai_person_material':
  summary['material_fields']=list(next(iter(after.values()),next(iter(before.values()),{})))
  summary['material_recall_disabled_existing_rows']=sum(bool(before[k].get('recall_allowed')) and not bool(after[k].get('recall_allowed')) for k in common)
db.close()
dest=S/'historical-data-diff-private.json';dest.write_text(json.dumps(private,ensure_ascii=False,default=str,indent=2));dest.chmod(0o600)
summary['private_details_sha256']=hashlib.sha256(dest.read_bytes()).hexdigest();(S/'historical-data-diff-summary.json').write_text(json.dumps(summary,ensure_ascii=False,default=str,indent=2));print(json.dumps({'production_writes':0,'tables':{t:{k:v for k,v in row.items() if not k.endswith('_ids')} for t,row in summary['tables'].items()},'current_wildcard_markers':summary.get('current_wildcard_markers')},ensure_ascii=False,default=str))
