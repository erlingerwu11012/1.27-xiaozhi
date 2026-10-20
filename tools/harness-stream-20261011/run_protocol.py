import argparse
cli=argparse.ArgumentParser();cli.add_argument('--name',default='protocol03');opt=cli.parse_args()
import os
os.environ['PROTOCOL_RUN_NAME']=opt.name
import bootstrap,unittest,json
from bootstrap import budget,stage
import experience_protocol
from experience_protocol import DeviceProtocol
from stateful_device import StatefulDevice
from test_support import SimulationManager
class LegacyDevice(StatefulDevice):
 def __init__(self):
  super().__init__()
  original=SimulationManager()
  for name in ('self_get_system_info','self_reboot','self_screen_get_info','self_screen_set_render_mode','self_screen_set_render_options','self_screen_get_render_status'):
   if name in original.tools:self.tools[name]=original.tools[name]
experience_protocol.SimulationManager=LegacyDevice
class CountedResult(unittest.TextTestResult):
 def startTest(self,test):self.charge=budget.reserve('case','protocol:'+test.id());super().startTest(test)
 def addSubTest(self,test,subtest,err):
  charge=budget.reserve('case','protocol-sub:'+str(subtest));budget.finish(charge,{'passed':err is None});super().addSubTest(test,subtest,err)
 def stopTest(self,test):budget.finish(self.charge,{'finished':True});super().stopTest(test)
suite=unittest.defaultTestLoader.loadTestsFromTestCase(DeviceProtocol)
r=unittest.TextTestRunner(verbosity=2,resultclass=CountedResult).run(suite)
(stage/(opt.name+'-summary.json')).write_text(json.dumps({'tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'budget':budget.report()},indent=2))
raise SystemExit(not r.wasSuccessful())
