from pathlib import Path
source=Path(__file__).with_name('runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
import os
os.environ['CANDIDATE_RUNTIME']='1'
exec(compile(source,'<prompt-inspection>','exec'));provider.client.close()
(OUT/'dialogue-fix-platform-base.txt').write_text(base.get('system_base_prompt',''))
(OUT/'dialogue-fix-assembled-prompt.txt').write_text(prompt)
print('platform_base_chars='+str(len(base.get('system_base_prompt',''))))
print(base.get('system_base_prompt',''))
