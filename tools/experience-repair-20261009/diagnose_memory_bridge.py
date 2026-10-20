import bootstrap,asyncio,json
from bootstrap import stage,budget
from wire_conversation import WireConversation
ns={'__name__':'helper'};code=(stage/'run_final.py').read_text(encoding='utf-8-sig');exec(code[:code.rindex('asyncio.run(main())')],ns)
class Fake:
 last_usage={}
 def decision(self,_):return {'mode':'chat','reply':'你好'}
async def main():
 import requests
 cfg=json.load(open('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json'));w=await WireConversation().setup(Fake(),cfg)
 try:
  budget.reserve('case','diagnostic-real-memory-bridge');ns['seed_memory'](w);a=w.c.person_turn.payload();r=requests.post('http://127.0.0.1:18002/xiaozhi/person-memory/internal/recent',json={'actor':a,'query':'喜欢的饮料'},headers=w.api_headers,timeout=3);print('direct',r.status_code,r.text)
  from config.manage_api_client import ManageApiClient
  client=ManageApiClient(w.c.config);print('api_base',str(client._async_client.base_url));print('via_client',await client.request('POST','person-memory/internal/recent',json={'actor':a,'query':'咖啡'},timeout=2))
 finally:await w.close()
asyncio.run(main())
