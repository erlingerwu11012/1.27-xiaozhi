import bootstrap,unittest,types
from unittest.mock import AsyncMock,MagicMock,patch
from test_followup import BudgetResult
from core.utils.device_speech_origin import note_device_speech
from core.handle.receiveAudioHandle import _startToChat
class Ingress(unittest.IsolatedAsyncioTestCase):
 def conn(self):return types.SimpleNamespace(session_id='s',logger=MagicMock(),need_bind=False,max_output_size=0,current_speaker=None,client_is_speaking=True,client_listen_mode='realtime',executor=MagicMock(),chat=MagicMock(),config={'harness':{'enabled':True}})
 async def test_device_echo_dropped_before_abort_and_dispatch(self):
  c=self.conn();note_device_speech(c,'提醒你拿外卖。',source='reminder')
  with patch('core.utils.proactive_return.handle_proactive_return',AsyncMock(return_value=False)),patch('core.utils.proactive_greeting.handle_proactive_greeting',AsyncMock(return_value=False)),patch('core.handle.receiveAudioHandle.handleAbortMessage',AsyncMock()) as abort,patch('core.handle.receiveAudioHandle.send_stt_message',AsyncMock()) as stt:
   await _startToChat(c,'提醒你拿外卖。',None)
   abort.assert_not_called();stt.assert_not_called();c.executor.submit.assert_not_called()
 async def test_old_connection_echo_cannot_suppress_new_user(self):
  c=self.conn();note_device_speech(c,'提醒你拿外卖。',source='reminder');c.session_id='new'
  with patch('core.utils.proactive_return.handle_proactive_return',AsyncMock(return_value=False)),patch('core.utils.proactive_greeting.handle_proactive_greeting',AsyncMock(return_value=False)),patch('core.handle.receiveAudioHandle.handleAbortMessage',AsyncMock()) as abort,patch('core.handle.receiveAudioHandle.send_stt_message',AsyncMock()) as stt:
   await _startToChat(c,'提醒你拿外卖。',None)
   abort.assert_awaited_once();stt.assert_awaited_once();c.executor.submit.assert_called_once()
if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=2,resultclass=BudgetResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(Ingress));raise SystemExit(not result.wasSuccessful())
