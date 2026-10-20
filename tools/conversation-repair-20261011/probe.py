import bootstrap,json,requests,uuid,dataclasses,asyncio
from bootstrap import stage,budget
from test_support import PACK
for t in PACK['tools']:
 if t['function']['name'] in {'add_reminder','habit_learn'}:print('SCHEMA',json.dumps(t,ensure_ascii=False))
from wire_conversation import WireConversation
class Fake:
 def decision(self,m):return {'mode':'chat','reply':'好。'}
async def main():
 cfg=json.loads(open('/root/prjs/tmp/harness-20261007/private-backup/runtime-config.json').read());w=await WireConversation().setup(Fake(),cfg)
 from core.utils.person_identity import activate,deactivate
 from core.utils.recent_memory import add,search,override
 token=activate(w.c,w.c.person_turn)
 try:
  budget.reserve('case','api-explicit-add');a=await add(w.c,'我的测试茶杯是蓝色');print('ADD',json.dumps(a,ensure_ascii=False));assert a.get('ok') is True
  budget.reserve('case','api-same-turn-readback');b=await search(w.c,'测试茶杯');print('SEARCH',json.dumps(b,ensure_ascii=False));assert '我的测试茶杯是蓝色' in b['text']
  budget.reserve('case','api-add-idempotent');a2=await add(w.c,'我的测试茶杯是蓝色');assert a2['record_id']==a['record_id']
  budget.reserve('case','api-id-version-correction');c=await override(w.c,'correct',replacement='我的测试茶杯是绿色',record_id=a['record_id'],expected_version=a['version']);print('CORRECT',json.dumps(c,ensure_ascii=False));assert c.get('ok') is True
  budget.reserve('case','api-correction-readback');d=await search(w.c,'测试茶杯');assert '绿色' in d['text'] and '蓝色' not in d['text']
  budget.reserve('case','api-id-version-forget');item=d['items'][0];f=await override(w.c,'forget',record_id=item['record_id'],expected_version=item['version']);assert f.get('ok') is True
  budget.reserve('case','api-forget-readback');d=await search(w.c,'测试茶杯');assert '绿色' not in d['text']
  budget.reserve('case','api-unauthorized');r=requests.post('http://127.0.0.1:18002/xiaozhi/person-memory/internal/add',json={'actor':w.c.person_turn.payload(),'fact':'测试'},timeout=3);assert r.status_code==401
 finally:deactivate(token);await w.close()
 print('BACKEND_PROBE_PASSED',budget.report())
asyncio.run(main())
