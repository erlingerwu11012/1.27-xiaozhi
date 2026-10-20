import asyncio
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
with patch('config.logger.setup_logging',return_value=MagicMock()):
    from core.providers.memory.bailian.bailian import MemoryProvider
    from core.utils.habit_router import _call_llm_with_tools
from core.utils.person_identity import PersonTurn, activate, deactivate

def actor():return PersonTurn('10','usr_a',0,4,'personal','matched','turn_a','device','agent',1,'voice_a',1)

class MemoryToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_automatic_search_parallel_budget_and_unknown(self):
        provider=MemoryProvider({});conn=SimpleNamespace(config={})
        self.assertEqual(await provider.query_memory('任意聊天'),'')
        self.assertEqual((await provider.search(conn,'历史'))['status'],'identity_unknown')
        token=activate(conn,actor())
        request=AsyncMock(return_value={'text':'个人事实'})
        try:
            with patch('config.manage_api_client.ManageApiClient') as client:
                client.return_value.request=request
                results=await asyncio.gather(provider.search(conn,'偏好'),provider.search(conn,'历史'))
                self.assertEqual(request.await_count,1)
                self.assertEqual(await provider.search(conn,'再问'),results[0])
        finally:deactivate(token)

class HabitToolFeedbackTests(unittest.TestCase):
    def test_actual_feedback_precedes_next_model_request(self):
        messages=[];closed=[];executed=[]
        call=SimpleNamespace(id='call_a',function=SimpleNamespace(name='habit_learn',arguments='{"hour":8}'))
        first=SimpleNamespace(tool_calls=[call],model_dump=lambda **kwargs:{'role':'assistant','tool_calls':[{'id':'call_a','type':'function','function':{'name':'habit_learn','arguments':'{"hour":8}'}}]})
        final=SimpleNamespace(tool_calls=[],model_dump=lambda **kwargs:{'role':'assistant','content':'真实结果已收到'})
        def create(**kwargs):
            messages.append(copy.deepcopy(kwargs['messages']))
            return SimpleNamespace(choices=[SimpleNamespace(message=first if len(messages)==1 else final)])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),close=lambda:closed.append(True))
        def execute(name,args):executed.append((name,args));return {'ok':False,'error':'设备存储失败'}
        with patch('openai.OpenAI',return_value=client),self.assertRaisesRegex(ValueError,'habit_execution_failed'):
            _call_llm_with_tools({'api_key':'synthetic','base_url':'http://example.test','model':'synthetic'},'摘要',[],execute)
        self.assertEqual(len(executed),1)
        self.assertEqual(json.loads(messages[1][-1]['content']),{'ok':False,'error':'设备存储失败'})
        self.assertTrue(closed)
    def test_failed_execution_keeps_analysis_unacknowledged(self):
        call=SimpleNamespace(id='call_a',function=SimpleNamespace(name='habit_learn',arguments='{}'))
        message=SimpleNamespace(tool_calls=[call],model_dump=lambda **kwargs:{'role':'assistant'})
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs:SimpleNamespace(choices=[SimpleNamespace(message=message)]))),close=lambda:None)
        with patch('openai.OpenAI',return_value=client),self.assertRaisesRegex(ValueError,'habit_execution_failed'):
            _call_llm_with_tools({'api_key':'synthetic','base_url':'http://example.test','model':'synthetic'},'摘要',[],lambda *args:False)
