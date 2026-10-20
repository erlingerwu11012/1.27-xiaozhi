import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).parent/'work/xiaozhi-server'))
import config.config_loader
config.config_loader.get_config_from_api=lambda cfg:dict(cfg,read_config_from_api=False)
import config.settings
config.settings.config_file_valid=True
import config.logger
config.logger.setup_logging=lambda:MagicMock()
from core.handle.textHandler.reminderEventMessageHandler import ReminderEventMessageHandler
from core.utils import reminder_interaction as ri

class EventProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn=SimpleNamespace(device_id='software',session_id='software-session',superseded=False,_outbound_tasks=set(),server=SimpleNamespace(is_current_connection=lambda device,conn:True))
        self.handler=ReminderEventMessageHandler();self.clock=patch.object(ri.time,'time',return_value=1000);self.clock.start()
        await self.event('interaction_opened',expires_at=1060)
    async def asyncTearDown(self):ri.on_connection_invalidated(self.conn);self.clock.stop()
    async def event(self,event,**kw):await self.handler.handle(self.conn,dict(event=event,instance_id='note:1',revision=2,**kw))
    async def test_renewed_event_recognized(self):
        await self.event('interaction_renewed',expires_at=1120);self.assertEqual(ri.get_interaction_state(self.conn).expires_at,1120)
    async def test_clipped_event(self):
        await self.event('interaction_renewed',expires_at=9999);self.assertEqual(ri.get_interaction_state(self.conn).expires_at,1180)
    async def test_close_wrong_revision(self):
        await self.handler.handle(self.conn,dict(event='interaction_closed',instance_id='note:1',revision=1,reason='resolved'));self.assertTrue(ri.is_interaction_active(self.conn))
    async def test_close_then_renew_does_not_reopen(self):
        await self.event('interaction_closed',reason='resolved');await self.event('interaction_renewed',expires_at=1120);self.assertFalse(ri.get_interaction_state(self.conn).active)
    async def test_superseded_connection_cannot_renew(self):
        self.conn.superseded=True;await self.event('interaction_renewed',expires_at=1120);self.assertEqual(ri.get_interaction_state(self.conn).expires_at,1060)

if __name__=='__main__':unittest.main()
