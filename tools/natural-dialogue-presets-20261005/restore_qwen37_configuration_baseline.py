import json
from pathlib import Path
out=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
exec((out/'inspect_qwen37_release_20261007.py').read_text().split('cfg=json.loads')[0])
old=json.loads(Path('/root/prjs/tmp/qwen37-official-release-20261007/backup-20261006-173418/database-private.json').read_text())
def q(s):return "'"+str(s).replace('\\','\\\\').replace("'","''")+"'"
updates=["UPDATE ai_model_config SET config_json="+q(json.dumps(old['model'],ensure_ascii=False))+" WHERE id='LLM_QwenPlusOfficial'","DELETE FROM one_api.abilities WHERE model='qwen3.7-plus' AND channel_id IN(8,11)",'UPDATE one_api.tokens SET models='+q(old['token']['models'])+' WHERE id=10']
updates+=['UPDATE one_api.channels SET models='+q(c['models'])+' WHERE id='+str(c['id']) for c in old['channels']]
sql('START TRANSACTION;'+';'.join(updates)+';COMMIT;')
print('configuration_baseline_restored; billing_ledgers_untouched')
