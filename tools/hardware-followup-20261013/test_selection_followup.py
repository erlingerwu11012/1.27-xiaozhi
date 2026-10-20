import bootstrap,unittest,time,json,collections
from test_followup import BudgetResult
from test_lifecycle_followup import HarnessLifecycle
from core.utils.tool_harness.runtime import selected_memory_ids
class Selection(HarnessLifecycle):
 async def test_broad_refresh_limited_to_selected_record(self):
  from core.utils.recent_memory import add,search
  w=await self.setup_wire();from core.utils.person_identity import activate
  self.direct_token=activate(w.c,w.c.person_turn);drink=await add(w.c,'我喜欢测试美式咖啡')
  import dataclasses,uuid
  from core.utils.person_identity import deactivate
  extra=activate(w.c,dataclasses.replace(w.c.person_turn,turn_id=uuid.uuid4().hex))
  try:wife=await add(w.c,'我妻子叫测试戊')
  finally:deactivate(extra)
  r=await search(w.c,'饮品',record_ids=[drink['record_id']]);h=w.c._full_tool_harness;h._memory_selection=(h.scope(),time.monotonic(),r['items'])
  self.plans({'mode':'operate','intent':'action','intent_evidence':'把这些记忆全删除了','authorized_writes':['memory_forget'],'finished':False,'steps':[{'id':'a','tool':'memory_search','arguments':{'query':'个人记忆','scope':'facts'}}]},
   {'mode':'operate','intent':'action','intent_evidence':'把这些记忆全删除了','authorized_writes':['memory_forget'],'steps':[{'id':'b','tool':'memory_forget','arguments':{'records':[{'record_id':drink['record_id'],'expected_version':drink['version'],'match':'我喜欢测试美式咖啡'}]}}]},
   {'mode':'chat','steps':[],'authorized_writes':[],'reply':'刚才查到的饮品偏好已删除。'})
  result=await w.turn('把这些记忆全删除了。');reads=[r for r in result['outcome']['results'] if r['tool']=='memory_search']
  self.assertEqual(reads[0]['arguments']['record_ids'],[drink['record_id']]);self.assertEqual(len(reads[0]['payload']['items']),1)
  self.assertTrue(any(r['tool']=='memory_forget' and r['state']=='completed' for r in result['outcome']['results']))
  kept=await search(w.c,'配偶',record_ids=[wife['record_id']]);self.assertEqual(kept['items'][0]['text'],'我妻子叫测试戊')
 async def asyncTearDown(self):
  if hasattr(self,'direct_token'):
   from core.utils.person_identity import deactivate
   deactivate(self.direct_token)
  await super().asyncTearDown()
 def test_expired_or_unrelated_scope_not_inherited(self):
  selected=('a',time.monotonic(),[{'record_id':'r'}])
  self.assertEqual(selected_memory_ids('把这些记忆删掉',selected,'a'),['r']);self.assertEqual(selected_memory_ids('删除另外的姓名',selected,'a'),[]);self.assertEqual(selected_memory_ids('把这些记忆删掉',selected,'b'),[])
if __name__=='__main__':
 suite=unittest.TestSuite([Selection('test_broad_refresh_limited_to_selected_record'),Selection('test_expired_or_unrelated_scope_not_inherited')]);result=unittest.TextTestRunner(verbosity=2,resultclass=BudgetResult).run(suite);raise SystemExit(not result.wasSuccessful())
