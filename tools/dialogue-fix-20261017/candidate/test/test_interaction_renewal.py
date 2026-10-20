import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from core.utils import reminder_interaction as ri

class RenewalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.conn=SimpleNamespace(_outbound_tasks=set());self.clock=patch.object(ri.time,'time',return_value=1000);self.clock.start()
        self.allowed=patch('core.utils.device_outbound.is_outbound_allowed',return_value=True);self.allowed.start()
        ri.open_interaction(self.conn,instance_id='note:1',revision=2,expires_at=1060)
    def tearDown(self):ri.on_connection_invalidated(self.conn);self.allowed.stop();self.clock.stop()
    def renew(self,**kw):return ri.renew_interaction(self.conn,instance_id=kw.get('instance_id','note:1'),revision=kw.get('revision',2),expires_at=kw.get('expires_at',1120))
    async def test_normal(self):
        ri.open_interaction(self.conn,instance_id='note:1',revision=2,expires_at=1060)
        old=self.conn._reminder_interaction_expire_task;self.assertTrue(self.renew()[0]);await asyncio.sleep(0);self.assertTrue(old.cancelled());self.assertIsNotNone(self.conn._reminder_interaction_expire_task);self.assertEqual(ri.get_interaction_state(self.conn).expires_at,1120)
    def test_clip(self):self.assertEqual(self.renew(expires_at=9000),(True,'expires_at_clipped'));self.assertEqual(ri.get_interaction_state(self.conn).expires_at,1180)
    def test_duplicate_and_older(self):
        for deadline in (1060,1050):self.assertEqual(self.renew(expires_at=deadline),(True,'unchanged'))
        self.assertEqual(ri.get_interaction_state(self.conn).expires_at,1060)
    def test_wrong_identity(self):
        for fields in ({'instance_id':'note:2'},{'revision':3},{'revision':True},{'revision':'2'}):self.assertFalse(self.renew(**fields)[0])
    def test_bad_deadline(self):
        for value in (True,'1120',1120.5,None,999):self.assertFalse(self.renew(expires_at=value)[0])
    def test_expired(self):
        ri.get_interaction_state(self.conn).expires_at=999;self.assertFalse(self.renew()[0]);self.assertFalse(ri.get_interaction_state(self.conn).active)
    def test_closed(self):ri.close_interaction(self.conn);self.assertFalse(self.renew()[0])
    def test_disconnected(self):ri.on_connection_invalidated(self.conn);self.assertFalse(self.renew()[0])
    def test_invalid_connection(self):
        with patch('core.utils.device_outbound.is_outbound_allowed',return_value=False):self.assertFalse(self.renew()[0])
    def test_old_close(self):
        self.assertFalse(ri.close_matching_interaction(self.conn,instance_id='note:2',revision=2,reason='resolved'));self.assertTrue(ri.is_interaction_active(self.conn))
        self.assertFalse(ri.close_matching_interaction(self.conn,instance_id='note:1',revision=1,reason='resolved'))
        self.assertTrue(ri.close_matching_interaction(self.conn,instance_id='note:1',revision=2,reason='resolved'))
    async def test_old_worker_cannot_close_renewed(self):
        old=ri.get_interaction_state(self.conn).generation
        with patch.object(ri.asyncio,'sleep',new=AsyncMock()):
            self.renew();await ri._interaction_expire_worker(self.conn,old)
        self.assertTrue(ri.get_interaction_state(self.conn).active)

if __name__=='__main__':unittest.main()
