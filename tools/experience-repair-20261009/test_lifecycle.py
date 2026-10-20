import bootstrap,json,sys,unittest,asyncio,dataclasses
from pathlib import Path
from bootstrap import stage,budget
from test_support import connection,decision,step
from core.utils.person_identity import PersonTurn,activate,deactivate
from test_unit import TestHarness
class LifecycleTests(unittest.IsolatedAsyncioTestCase):
 async def test_queued_listen_switch_keeps_request(self):
  c,m,h=connection(decide=lambda _:decision(step('self_audio_speaker_set_volume',{'volume':30})))
  await h.lock.acquire();task=asyncio.create_task(h.run('把音量调到30',[]));await asyncio.sleep(0);c.listen_epoch+=1;h.lock.release();out=await task
  self.assertFalse(out.interrupted);self.assertEqual(out.results[-1].state,'completed')
 async def test_queued_identity_change_stops_request(self):
  c,m,h=connection();a=PersonTurn('a','p',0,1,'personal','matched','t','d','agent',1);c.person_turn=a;token=activate(c,a)
  try:
   await h.lock.acquire();task=asyncio.create_task(h.run('把音量调到30',[]));await asyncio.sleep(0);c.person_turn=dataclasses.replace(a,person_id='other');h.lock.release();out=await task
   self.assertTrue(out.interrupted);self.assertFalse(m.calls)
  finally:deactivate(token)
 async def test_chat_identity_change_stops_response(self):
  c,m,h=connection();a=PersonTurn('a','p',0,1,'personal','matched','t','d','agent',1);c.person_turn=a;token=activate(c,a)
  try:
   def decide(_):c.person_turn=dataclasses.replace(a,person_id='other');return {'mode':'chat','reply':'你好'}
   h.decide=decide;out=await h.run('你好',[]);self.assertTrue(out.interrupted)
  finally:deactivate(token)
 async def test_frozen_speaker_recipient_and_unknown_clarification(self):
  from types import SimpleNamespace
  from unittest.mock import patch,AsyncMock
  from core.utils.recipient_resolver import ProfileDirectory,ProfileRecord
  from core.utils.unified_recipient_resolver import resolve_unified_recipient_for_conn
  directory=ProfileDirectory(account_id='a',profiles=[ProfileRecord('usr_a','小明','active','a'),ProfileRecord('usr_b','小红','active','a')])
  c=SimpleNamespace(config={},account_id='a',device_id='d',current_speaker_user={'user_id':'spoofed'})
  a=PersonTurn('a','usr_a',0,1,'personal','matched','t','d','agent',1,display_name='小明');token=activate(c,a)
  try:
   with patch('core.utils.unified_recipient_resolver._fetch_directory',AsyncMock(return_value=directory)):
    for text,expected in [('提醒喝水','usr_a'),('提醒我喝水','usr_a'),('提醒小红喝水','usr_b')]:
     r=await resolve_unified_recipient_for_conn(c,user_text=text);self.assertEqual(r.recipient_person_id,expected)
  finally:deactivate(token)
  with patch('core.utils.unified_recipient_resolver._fetch_directory',AsyncMock(return_value=directory)):
   r=await resolve_unified_recipient_for_conn(c,user_text='提醒我喝水');self.assertFalse(r.ok_for_create);self.assertIn('身份',r.message)
   r=await resolve_unified_recipient_for_conn(c,user_text='公共提醒喝水',selector='all');self.assertEqual(r.recipient_person_id,'all')
class Result(unittest.TextTestResult):
 def startTest(self,t):budget.reserve('case',t.id());super().startTest(t)
suite=unittest.defaultTestLoader.loadTestsFromTestCase(LifecycleTests)
suite.addTest(TestHarness('test_catalog_raw_binding_change_stops_execution'))
r=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
(stage/'lifecycle-summary.json').write_text(json.dumps({'tests':r.testsRun,'failures':[(str(t),s) for t,s in r.failures],'errors':[(str(t),s) for t,s in r.errors],'budget':budget.report()},ensure_ascii=False));sys.exit(not r.wasSuccessful())
