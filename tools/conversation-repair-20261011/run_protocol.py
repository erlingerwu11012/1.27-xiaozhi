import bootstrap,unittest,sys,json
from bootstrap import budget,stage
import experience_protocol as p
from stateful_device import StatefulDevice
from core.utils.recipient_resolver import ProfileDirectory,ProfileRecord
from unittest.mock import patch,AsyncMock
p.SimulationManager=StatefulDevice
class Result(unittest.TextTestResult):
 def startTest(self,t):budget.reserve('case','protocol:'+t.id());super().startTest(t)
 def addSubTest(self,t,s,e):budget.reserve('case','protocol-sub:'+str(s));super().addSubTest(t,s,e)
suite=unittest.defaultTestLoader.loadTestsFromTestCase(p.DeviceProtocol)
directory=ProfileDirectory(account_id='simulation-account',profiles=[ProfileRecord('person-a','测试用户','active','simulation-account')])
with patch('core.utils.unified_recipient_resolver._fetch_directory',AsyncMock(return_value=directory)):
 r=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
(stage/'protocol-summary.json').write_text(json.dumps({'tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'budget':budget.report()}))
sys.exit(not r.wasSuccessful())
