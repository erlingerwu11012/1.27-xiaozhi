"""Read aggregate test credential balances without printing any credential."""
import os,json
from pathlib import Path
os.environ['CANDIDATE_RUNTIME']='1'
source=Path(__file__).with_name('runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
exec(compile(source,'<bootstrap>','exec'));provider.client.close()
for kind,cfg in [('llm',llm),('tts',model_config('TTS_QwenAudioTTSPlus'))]:
 token=cfg['api_key'];token=token[3:] if token.startswith('sk-') else token
 assert all(c.isalnum() or c in '_-' for c in token)
 values=sql("SELECT id,user_id,remain_quota,unlimited_quota,used_quota FROM one_api.tokens WHERE `key`='"+token+"' LIMIT 1;")
 fields=values.split('\t')
 user=sql('SELECT quota,used_quota FROM one_api.users WHERE id='+str(int(fields[1]))+';')
 print(json.dumps({'kind':kind,'token_id':int(fields[0]),'user_id':int(fields[1]),
    'token_remaining_units':int(fields[2]),'token_unlimited':fields[3],
    'token_used_units':int(fields[4]),'account_quota_units':user.split('\t'),
    'hardware_context_configured':bool(cfg.get('_hardware_billing'))}))
 print(json.dumps({'kind':kind,'model_limits':sql('SELECT models FROM one_api.tokens WHERE id='+str(int(fields[0]))+';')}))
