import json,hashlib
from pathlib import Path
s=Path(__file__).parent;p=s/'cases-v2.json';pack=json.loads(p.read_text(encoding='utf-8'))
changes=[]
for g in pack['groups']:
 if g['kind']==9:
  row=g['turns'][2];row['legacy_expected']=dict(row);row.update(tool=None,clarify=True,card=False);row.pop('card_action',None)
  changes.append({'group':g['id'],'turn':2,'reason':'Firmware Act clears current_instance_id and GetCurrentJson returns active=false after secondary; preserve original request but expect clarification before any further write.','source':'main/reminder_coordinator.cc:2280; main/mcp_tools/mcp_tools_card.cc:164','old_expected':row['legacy_expected']})
pack['fixture_corrections']=changes
p.write_text(json.dumps(pack,ensure_ascii=False,indent=2),encoding='utf-8');(s/'cases-v2.sha256').write_text(hashlib.sha256(p.read_bytes()).hexdigest())
(s/'fixture-corrections.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding='utf-8')
print('preserved original requests; corrected protocol expectations',len(changes))
