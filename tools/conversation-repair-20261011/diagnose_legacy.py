import bootstrap,sys,traceback
from bootstrap import stage,budget
sys.path.insert(0,str(stage/'work/test'))
from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests as T
T.setUpClass();t=T('test_no_tools_streams_chunks_without_duplicate_full_answer');t.setUp()
budget.reserve('case','legacy-regression-diagnostic')
try:
 h=t.handler(functions=None);h.logger.exception.side_effect=lambda *a,**k:traceback.print_exc()
 from unittest.mock import MagicMock
 h.llm.response=MagicMock(return_value=iter(['先说','后说']))
 print('RESULT',t.chat(h))
finally:t.doCleanups();T.tearDownClass()
