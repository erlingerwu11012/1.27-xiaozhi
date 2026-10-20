import unittest
from unittest.mock import patch, AsyncMock
import httpx
import app

class HabitApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app.broadcast_app.state.config={'manager-api':{'secret':'test-habit-service'}}
        self.http=httpx.AsyncClient(transport=httpx.ASGITransport(app=app.broadcast_app),base_url='http://test')
        self.sync=patch('core.utils.habit_sync.synchronize_habit',new=AsyncMock(return_value={'ok':True,'sync_state':'synced'}));self.mock=self.sync.start()
    async def asyncTearDown(self):await self.http.aclose();self.sync.stop()
    async def test_no_auth(self):
        self.assertEqual((await self.http.post('/api/v1/habit/sync',json={'habit_id':1})).status_code,401);self.mock.assert_not_awaited()
    async def test_wrong_key(self):
        r=await self.http.post('/api/v1/habit/sync',headers={'Authorization':'Bearer wrong'},json={'habit_id':1});self.assertEqual(r.status_code,401);self.mock.assert_not_awaited()
    async def test_no_query_key(self):
        r=await self.http.post('/api/v1/habit/sync?secret=test-habit-service',headers={'Authorization':'Bearer test-habit-service'},json={'habit_id':1});self.assertEqual(r.status_code,401);self.mock.assert_not_awaited()
    async def test_body_cannot_claim_account(self):
        for body in ({'habit_id':1,'account_id':'42'},{'habit_id':True},{'habit_id':0},{'habit_id':'1'},{'habit_id':1,'payload':{}},{'habit_id':1,'device_id':'other'}):
            r=await self.http.post('/api/v1/habit/sync',headers={'Authorization':'Bearer test-habit-service'},json=body);self.assertEqual(r.status_code,400)
        self.mock.assert_not_awaited()
    async def test_authenticated(self):
        r=await self.http.post('/api/v1/habit/sync',headers={'Authorization':'Bearer test-habit-service'},json={'habit_id':1});self.assertTrue(r.json()['ok']);self.mock.assert_awaited_once()
    async def test_management_failure_is_not_success(self):
        self.mock.side_effect=RuntimeError('private error');r=await self.http.post('/api/v1/habit/sync',headers={'Authorization':'Bearer test-habit-service'},json={'habit_id':1});self.assertEqual(r.status_code,503);self.assertNotIn('private error',r.text)

if __name__=='__main__':unittest.main()
