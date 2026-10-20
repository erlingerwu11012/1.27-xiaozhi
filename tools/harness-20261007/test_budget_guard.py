import concurrent.futures,tempfile,unittest
from pathlib import Path
import budget_guard as b
class BudgetTests(unittest.TestCase):
 def test_threads_cannot_overspend(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'b.sqlite';b.initialize(p,prior_rows=0,request_limit=10,row_limit=20)
   def reserve(_):
    try:b.reserve('requests',p);return True
    except b.BudgetExceeded:return False
   with concurrent.futures.ThreadPoolExecutor(max_workers=8) as e:self.assertEqual(sum(e.map(reserve,range(30))),10)
   self.assertEqual(b.snapshot(p)['requests']['used'],10)
 def test_record_limit_and_no_reset(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'b.sqlite';b.initialize(p,prior_rows=1,request_limit=5,row_limit=2)
   b.reserve('records',p)
   with self.assertRaises(b.BudgetExceeded):b.reserve('records',p)
   b.initialize(p,prior_rows=0,request_limit=100,row_limit=100)
   self.assertEqual(b.snapshot(p)['records'],{'used':2,'limit':2})
 def test_with_options_shares_request_hook(self):
  import httpx,openai,types
  with tempfile.TemporaryDirectory() as d:
   old=b.PATH;b.PATH=Path(d)/'b.sqlite'
   try:
    client=openai.OpenAI(api_key='fake-test-only',base_url='https://no-network.invalid/v1',http_client=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'id':'x','choices':[],'model':'fake','object':'chat.completion','created':0}))))
    b.attach(types.SimpleNamespace(client=client))
    client.chat.completions.create(model='fake',messages=[])
    client.with_options(max_retries=0).chat.completions.create(model='fake',messages=[])
    self.assertEqual(b.snapshot()['requests']['used'],2)
    client.close()
   finally:b.PATH=old
if __name__=='__main__':unittest.main(verbosity=2)
