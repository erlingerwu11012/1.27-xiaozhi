import json
from pathlib import Path
P=Path('/root/prjs/tmp/harness-20261007/private-backup')
for name in ['runtime-config.json','device-config.json']:
 c=json.loads((P/name).read_text());s=c.get('selected_module',{}).get('TTS');d=c.get('TTS',{}).get(s,{})
 print(name,{'selected':s,'type':d.get('type'),'model':d.get('model'),'official_enhanced':d.get('official_enhanced'),'official_billing':d.get('official_billing'),'has_key':bool(d.get('api_key')),'customer_fields':[k for k in c if 'context' in k or 'tts' in k.lower()]})
