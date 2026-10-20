import bootstrap,sys,traceback
sys.path.insert(0,str(bootstrap.work/'test'))
from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests as T
bootstrap.budget.reserve('case','diagnose_old_tts_fixture')
T.setUpClass();t=T();t.setUp();h=t.handler();t.primary_with_tools(h,['hello']);h.logger.exception.side_effect=lambda *a,**kw:traceback.print_exc();print('result',t.chat(h));t.doCleanups();T.tearDownClass()
