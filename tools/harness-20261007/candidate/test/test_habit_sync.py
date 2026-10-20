import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from core.utils.habit_sync import verified_receipt, synchronize_habit

class HabitSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.payload=dict(account_id='42',sync_id='9',recipient_person_id='usr_abc',recipient_display_name='张',intent='drink',description='喝水',hour=8,minute=0,advance_minutes=2,repeat_days=127,enabled=True,content_hash='a'*64)
        self.record=dict(ok=True,device_id='dev',config_version='1',payload=self.payload)
        self.api=SimpleNamespace(request=AsyncMock(side_effect=lambda method,path,**kw: self.record if method=='GET' else {'accepted':True}))
        self.conn=SimpleNamespace(config={'sys_user_id':'42'},session_id='sid',mcp_client=SimpleNamespace(capabilities={'experimental':{'habitSync':1}}),identity_synced_version=3)
        self.server=SimpleNamespace(get_current_main_session_id=lambda device:'sid',_connections={'dev':{'sid':self.conn}})
        self.result=dict(ok=True,persisted=True,sync_id='9',content_hash='a'*64,device_rule_id=5,enabled=True)
        self.patchers=[patch('config.manage_api_client.ManageApiClient',return_value=self.api),patch('core.utils.device_outbound.is_outbound_allowed',return_value=True),patch('core.utils.person_identity.refresh_directory',new=AsyncMock(return_value={'account_id':'42','directory_version':3})),patch('core.utils.person_directory_sync.private_rpc',new=AsyncMock(return_value=self.result))]
        for p in self.patchers:p.start()
        self.rpc=__import__('core.utils.person_directory_sync',fromlist=['private_rpc']).private_rpc
    def tearDown(self):
        for p in reversed(self.patchers):p.stop()
    async def run_sync(self):return await synchronize_habit({},self.server,9)
    async def test_saved(self):
        self.assertTrue((await self.run_sync())['ok']);self.rpc.assert_awaited_once();self.assertEqual(self.rpc.call_args.args[1],'habit/sync')
    async def test_false_transport_success(self):
        self.rpc.return_value={'ok':True,'sent':True};self.assertEqual((await self.run_sync())['error'],'invalid_receipt')
    async def test_receipt_contract(self):
        for key,value in [('persisted',False),('sync_id','8'),('content_hash','b'*64),('device_rule_id',True),('device_rule_id',0),('enabled',False)]:
            bad=dict(self.result);bad[key]=value;self.assertFalse(verified_receipt(bad,self.payload),(key,value))
    async def test_foreign_account(self):
        self.conn.config['sys_user_id']='43';self.assertEqual((await self.run_sync())['error'],'ownership_mismatch');self.rpc.assert_not_awaited()
    async def test_offline(self):
        self.server._connections={};self.assertEqual((await self.run_sync())['error'],'device_offline');self.rpc.assert_not_awaited()
    async def test_legacy_firmware(self):
        self.conn.mcp_client.capabilities={};self.assertEqual((await self.run_sync())['sync_state'],'upgrade_required');self.rpc.assert_not_awaited()
    async def test_missing_binding(self):
        self.record.update(ok=False,error='needs_binding');self.assertEqual((await self.run_sync())['error'],'needs_binding');self.rpc.assert_not_awaited();self.assertEqual(self.api.request.await_count,1)
    async def test_directory_not_synced(self):
        self.conn.identity_synced_version=2;self.assertEqual((await self.run_sync())['error'],'directory_not_ready');self.rpc.assert_not_awaited()
    async def test_storage_failure(self):
        self.rpc.return_value={'ok':False,'error':'storage_full'};self.assertEqual((await self.run_sync())['error'],'storage_full');self.assertEqual(self.api.request.call_args.kwargs['json']['state'],'failed')
    async def test_timeout_then_reconcile(self):
        self.rpc.side_effect=[asyncio.TimeoutError(),self.result];self.assertEqual((await self.run_sync())['error'],'receipt_timeout');self.assertTrue((await self.run_sync())['ok']);self.assertEqual(self.rpc.call_args_list[0].args[2],self.rpc.call_args_list[1].args[2])
    async def test_changed_config_during_rpc(self):
        self.api.request.side_effect=lambda method,path,**kw: self.record if method=='GET' else {'accepted':False}
        self.assertEqual((await self.run_sync())['error'],'configuration_changed')
    async def test_disabled_ack(self):
        self.payload['enabled']=False;self.result.update(enabled=False,device_rule_id=0);self.assertTrue((await self.run_sync())['ok'])
    async def test_duplicate_serialized(self):
        active=0;maximum=0
        async def rpc(*args,**kw):
            nonlocal active,maximum
            active+=1;maximum=max(active,maximum);await asyncio.sleep(.01);active-=1;return self.result
        self.rpc.side_effect=rpc
        outcomes=await asyncio.gather(self.run_sync(),self.run_sync());self.assertTrue(all(x['ok'] for x in outcomes));self.assertEqual(maximum,1)

if __name__=='__main__':unittest.main()
