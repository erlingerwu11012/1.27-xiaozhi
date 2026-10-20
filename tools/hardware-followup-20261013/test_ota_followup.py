"""Real isolated manager API and persisted OTA state; no device or download."""
from test_followup import API,HEADERS,sql,BudgetResult
import requests,unittest,uuid,concurrent.futures

class OtaFollowup(unittest.TestCase):
 def setUp(self):
  self.task=str(uuid.uuid4());self.device='followup-soft-'+uuid.uuid4().hex[:12];self.pack='followup-pack-'+uuid.uuid4().hex[:12]
  sql('INSERT INTO ai_role_deploy_task(task_id,device_id,role_pack_id,pack_id,requested_by,state,progress,attempt_count) VALUES(%s,%s,99003,%s,99003,%s,0,1)',(self.task,self.device,self.pack,'sent'))
 def ack(self,phase,**extra):
  payload={'task_id':self.task,'pack_id':self.pack,'phase':phase,**extra}
  return requests.post(API+'/role-packs/device/ack',headers={**HEADERS,'X-Device-Id':self.device},json=payload,timeout=8).json()
 def row(self):
  row=sql('SELECT state,progress,retry_count,error_message FROM ai_role_deploy_task WHERE task_id=%s',(self.task,),True)[0]
  return dict(zip(['state','progress','retry_count','error_message'],row))
 def busy(self,reason):
  result=self.ack('failed',error='E_BUSY',reason=reason,not_accepted=True)
  self.assertEqual(result['code'],0,result);row=self.row()
  self.assertEqual(row['state'],'retrying');self.assertEqual(row['retry_count'],1);self.assertIn(reason,row['error_message'])
  self.assertEqual(result['data']['state'],row['state'])
 def test_busy_state(self):self.busy('device_state_ineligible')
 def test_busy_task(self):self.busy('spine_task_running')
 def test_busy_resource(self):self.busy('wallpaper_resource_lock')
 def test_busy_worker(self):self.busy('worker_creation_failed')
 def test_unknown_never_resends(self):
  for error in ['E_BUSY','E_NETWORK']:
   sql('UPDATE ai_role_deploy_task SET state=%s WHERE task_id=%s',('sent',self.task))
   self.assertEqual(self.ack('failed',error=error)['code'],0)
   self.assertEqual(self.row()['state'],'needs_manual_review');self.assertEqual(self.row()['retry_count'],0)
 def test_phase_success_only_once(self):
  for phase,state,progress in [('waiting','accepted',0),('downloading','in_progress',30),('verifying','in_progress',75),('applying','in_progress',95)]:
   self.assertEqual(self.ack(phase,progress=progress)['code'],0)
   self.assertEqual(self.row()['state'],state)
   self.assertNotEqual(self.row()['state'],'completed')
  self.assertEqual(self.ack('success',progress=100)['code'],0);self.assertEqual(self.row()['state'],'completed')
  self.assertEqual(self.ack('success')['code'],0)
  self.assertEqual(self.ack('failed',error='E_BUSY',not_accepted=True)['code'],0)
  self.assertEqual(self.row()['state'],'completed');self.assertEqual(self.row()['retry_count'],0)
 def test_foreign_identity_and_pack_denied(self):
  original=self.device;self.device='another-soft-device'
  self.assertNotEqual(self.ack('success')['code'],0);self.device=original
  self.assertNotEqual(self.ack('success',pack_id='wrong-pack')['code'],0)
  self.assertEqual(self.row()['state'],'sent')
 def test_repeat_busy_receipt_does_not_spend_retries(self):
  self.busy('spine_task_running')
  for _ in range(3):self.assertEqual(self.ack('failed',error='E_BUSY',reason='spine_task_running',not_accepted=True)['code'],0)
  self.assertEqual(self.row()['state'],'retrying');self.assertEqual(self.row()['retry_count'],1)
 def test_retry_exhaustion_is_terminal(self):
  sql('UPDATE ai_role_deploy_task SET retry_count=100 WHERE task_id=%s',(self.task,))
  self.assertEqual(self.ack('failed',error='E_BUSY',reason='spine_task_running',not_accepted=True)['code'],0)
  self.assertEqual(self.row()['state'],'needs_manual_review')

if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2,resultclass=BudgetResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(OtaFollowup))
 raise SystemExit(not result.wasSuccessful())
