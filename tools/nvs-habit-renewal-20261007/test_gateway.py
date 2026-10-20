import os,sys,unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock,MagicMock
sys.path.insert(0,str(Path(__file__).parent/'work/gateway'))
from tools import habit_tool as h
class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def send(self,response,status=200):
        client=MagicMock();client.post=AsyncMock(return_value=MagicMock(status_code=status,json=lambda:response))
        client.__aenter__=AsyncMock(return_value=client);client.__aexit__=AsyncMock(return_value=None)
        with patch.dict(os.environ,{'HABIT_SERVICE_SECRET':'test-key'}),patch.object(h.httpx,'AsyncClient',return_value=client):
            out=await h._sync_habit_to_device({'id':9})
        return out,client.post
    async def test_transport_is_not_saved(self):self.assertFalse((await self.send({'ok':True,'sent':True}))[0])
    async def test_rejected_auth(self):self.assertFalse((await self.send({'ok':False},401))[0])
    async def test_saved_receipt_and_only_id(self):
        okay,post=await self.send({'ok':True,'sync_state':'synced','sync_id':'9','content_hash':'a'*64,'device_rule_id':5});self.assertTrue(okay);self.assertEqual(post.call_args.kwargs['json'],{'habit_id':9});self.assertEqual(post.call_args.kwargs['headers'],{'Authorization':'Bearer test-key'})
    async def test_foreign_id(self):self.assertFalse((await self.send({'ok':True,'sync_state':'synced','sync_id':'10','content_hash':'a'*64,'device_rule_id':5}))[0])
    async def test_mcp_cannot_claim_unbound_account(self):
        with patch.object(h,'_get_pool',new=AsyncMock()) as db:
            self.assertTrue((await h.habit_create(description='喝水',device_id='other',account_id='42'))['isError']);self.assertTrue((await h.habit_list_manual(account_id='42'))['isError']);db.assert_not_awaited()
if __name__=='__main__':unittest.main()
