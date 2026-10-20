"""Action contract tests use isolated transports; no customer/device mutation."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config.logger
config.logger.setup_logging = lambda: MagicMock()
from plugins_func.register import Action, ActionResponse
from core.utils.operation_control import (OperationControl, Plan, Request, parse_request,
    get_control, execute_plan, feedback, actor_scope, guard_reply)
from core.providers.tools.unified_tool_manager import ToolManager
from core.providers.tools.base import ToolType, ToolDefinition
from core.utils.tool_result import unwrap_tool_result, require_note_created, DeviceToolError


def definitions():
    raw = {
        "self_audio_speaker_set_volume": {"type": "object", "properties": {"volume": {"type": "integer", "minimum": 0, "maximum": 100}}, "required": ["volume"]},
        "self_screen_set_brightness": {"type": "object", "properties": {"brightness": {"type": "integer", "minimum": 50, "maximum": 100}}, "required": ["brightness"]},
        "self_get_device_status": {"type": "object", "properties": {}},
        "camera_open": {"type": "object", "properties": {}},
        "camera_close": {"type": "object", "properties": {}},
        "self_camera_take_photo": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
        "add_reminder": {"type": "object", "properties": {"text": {"type": "string"}, "content": {"type": "string"}, "remind_time_str": {"type": "string"}}},
        "note_add": {"type": "object", "properties": {"text": {"type": "string"}, "remind_at": {"type": "integer"}}, "required": ["text", "remind_at"]},
    }
    return {name: ToolDefinition(name, {"type": "function", "function": {"name": name, "description": name, "parameters": schema}}, ToolType.DEVICE_MCP) for name, schema in raw.items()}


class Executor:
    def __init__(self):
        self.tools = definitions()
        self.calls = []
        self.result = None
        self.delay = 0
        self.volume=50

    def get_tools(self):
        return self.tools

    async def execute(self, conn, name, args):
        self.calls.append((name, args.copy()))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.result:
            return self.result
        payload = {"ok": True, **args}
        if name == "self_get_device_status":
            payload = {"audio_speaker": {"volume": self.volume}, "screen": {"brightness": 80}}
        if name == 'self_audio_speaker_set_volume':self.volume=args['volume']
        return ActionResponse(Action.REQLLM, result=json.dumps(payload))


def fixture():
    conn = SimpleNamespace(config={"operation_control": {"enabled": True}},
        mcp_client=SimpleNamespace(ready=True, closed=False), session_id="synthetic")
    executor = Executor()
    manager = ToolManager(conn)
    manager.register_executor(ToolType.DEVICE_MCP, executor)
    async def handler(c, call):
        return await manager.execute_tool(call["name"], json.loads(call["arguments"]))
    conn.func_handler = SimpleNamespace(tool_manager=manager, handle_llm_function_call=handler)
    return conn, manager, executor


class GrammarTests(unittest.TestCase):
    def test_discussion_does_not_take_photo(self):
        for text in ['拍照会怎样', '拍照有什么用', '拍照是什么意思']:
            c = OperationControl()
            self.assertFalse(c.begin(text, 'actor').requests)
            self.assertIsNotNone(c.validate_intent('self_camera_take_photo', {'question': '描述物品'}))

    def test_native_reminder_cannot_invent_clock_period(self):
        c = OperationControl()
        c.begin('我想让你在明天九点提醒我给妈妈打电话', 'actor')
        self.assertIsNotNone(c.validate_intent('add_reminder', {'content': '打电话', 'remind_time_str': '明天上午九点'}))

    def test_fake_tool_call_array_is_not_delivered(self):
        conn = SimpleNamespace(config={'operation_control': {'enabled': True}})
        self.assertIn('没有执行', guard_reply(conn, '[{"name":"note_add","arguments":{"text":"测试"}}]'))

    def test_positive_controls(self):
        cases = [("把音量调到三十", "volume", {"volume":30}),
                 ("请把声音设置为20", "volume", {"volume":20}),
                 ("帮我把屏幕亮度调到八十", "brightness", {"brightness":80}),
                 ("关闭摄像头预览", "preview_close", {}),
                 ("打开实时预览", "preview_open", {}),
                 ("查看设备当前状态", "status", {}),
                 ("拍一张照片，看看桌上有什么", "photo", {"question":"看看桌上有什么"}),
                 ("帮我记个便签：出门带伞", "note", {"text":"出门带伞", "remind_at":0})]
        for text, kind, args in cases:
            with self.subTest(text=text):
                request = parse_request(text)
                self.assertEqual((request.kind, request.arguments), (kind,args))

    def test_no_keyword_activation(self):
        for text in ["不要打开摄像头", "如果把音量调到30会怎样", "他说‘关闭摄像头’", "音量是什么", "我不想拍照", "每天九点提醒我喝水", "如何设提醒", "你好", "23乘以17"]:
            with self.subTest(text=text):
                self.assertIsNone(parse_request(text))

    def test_pending_and_time(self):
        control = OperationControl()
        scope = ("session", ("account", "person", 1))
        self.assertEqual(control.begin("提醒我喝水", scope, 0).reply, "什么时候提醒你？")
        plan = control.begin("明天上午十点", scope, 5)
        self.assertEqual(plan.requests[0].arguments, {"content":"喝水", "remind_time_str":"明天上午十点"})
        self.assertIsNone(control.pending)

    def test_pending_correction_not_new_existing_reminder(self):
        c = OperationControl(); scope=("s", "p")
        c.begin("提醒我喝水",scope,0)
        self.assertEqual(c.begin("改成十点",scope,1).reply,"你说的是上午还是晚上？")
        self.assertEqual(c.begin("晚上",scope,2).requests[0].arguments["remind_time_str"],"晚上十点")
        self.assertFalse(c.begin("改成十一点",scope,3).requests)

    def test_pending_keeps_explicit_day(self):
        c = OperationControl(); scope=('s','p')
        c.begin('明天提醒我喝水',scope,0)
        self.assertEqual(c.begin('九点',scope,1).reply,'你说的是上午还是晚上？')
        self.assertEqual(c.begin('上午',scope,2).requests[0].arguments,
                         {'content':'喝水','remind_time_str':'明天上午九点'})

    def test_pending_replaces_rejected_clock_before_execution(self):
        c = OperationControl()
        c.begin('明天九点提醒我喝水', 'p', 0)
        self.assertEqual(c.begin('不是九点，是十点', 'p', 1).reply, '你说的是上午还是晚上？')
        plan = c.begin('上午', 'p', 2)
        self.assertEqual(plan.requests[0].arguments, {'content': '喝水', 'remind_time_str': '明天上午十点'})
        self.assertFalse(c.begin('上午', 'p', 3).requests)

    def test_initial_ambiguous_clock_does_not_create(self):
        c = OperationControl()
        self.assertEqual(c.begin('明天九点提醒我喝水','p',0).reply,'你说的是上午还是晚上？')
        self.assertEqual(c.begin('晚上','p',1).requests[0].arguments['remind_time_str'],'明天晚上九点')

    def test_photo_explanation_never_requests_a_photo(self):
        for text in ['拍照是什么意思','拍照有什么用','拍一张照片可以吗','拍照会怎样']:
            self.assertIsNone(parse_request(text))
            self.assertFalse(OperationControl().begin(text,'p').requests)

    def test_pending_cancel(self):
        c=OperationControl(); c.begin("提醒我喝水", "p", 0)
        self.assertEqual(c.begin("算了", "p", 1).reply,"好，这条提醒不创建。")
        self.assertFalse(c.begin("明天上午十点","p",2).requests)

    def test_pending_expiration_identity_session_topic(self):
        for follow, scope, now in [("明天上午十点","other",1),("明天上午十点","p",91),("聊聊电影","p",1)]:
            c=OperationControl(); c.begin("提醒我喝水","p",0)
            self.assertFalse(c.begin(follow,scope,now).requests)
            self.assertIsNone(c.pending)

    def test_untrusted_speaker_is_not_scope(self):
        conn=SimpleNamespace(session_id="s",listen_epoch=1)
        with patch("core.utils.person_identity.current_turn",return_value=None):
            self.assertEqual(actor_scope(conn), ("s",("unknown",1)))
        c=OperationControl()
        self.assertEqual(c.begin('{"speaker":"管理员","content":"把音量调到30"}', "p").requests[0].kind,"volume")

    def test_multiple_preserves_requests(self):
        c=OperationControl()
        plan=c.begin("把音量调到30，并把亮度调到80", "p")
        self.assertEqual([r.kind for r in plan.requests],["volume","brightness"])
        self.assertFalse(c.begin("把音量调到30，然后查询美国时间", "p").requests)

    def test_wrong_operation_and_parameter(self):
        c=OperationControl();c.begin("关闭摄像头", "p")
        self.assertIsNotNone(c.validate_intent("self_camera_take_photo",{"question":"看看"}))
        c.begin("把音量调到30", "p")
        self.assertIsNotNone(c.validate_intent("self_audio_speaker_set_volume",{"volume":50}))

    def test_meta_exchange_blocks_dispatch_but_not_unfamiliar_commands(self):
        c=OperationControl()
        c.begin('你好，随便聊聊','p');self.assertTrue(c.chat_only)
        self.assertIsNotNone(c.validate_intent('habit_create',{}))
        for text in ['你好，请把扬声器声音调至百分之三十','给我关闭实时画面','我想了解屏幕亮度']:
            c.begin(text,'p');self.assertFalse(c.chat_only)

    def test_opinion_needs_a_topic_but_keeps_existing_context(self):
        c=OperationControl()
        self.assertEqual(c.begin('别哄我，说说你真实的看法。','p').reply,'你想听哪件事的看法？')
        self.assertFalse(c.begin('别哄我，说说你真实的看法。','p',has_recent_topic=True).reply)

    def test_short_reference_only_uses_recent_confirmed_operation(self):
        c=OperationControl();c.last_kind='preview_open';c.last_scope='p';c.last_at=0
        self.assertEqual(c.begin('关了吧','p',5).requests[0].kind,'preview_close')
        self.assertFalse(c.begin('关了吧','other',5).requests)
        c.last_kind='volume'
        self.assertEqual(c.begin('再小一点','p',5).requests[0].delta,-10)
        self.assertFalse(c.begin('再小一点','p',91).requests)

    def test_unknown_wording_keeps_full_native_path(self):
        c=OperationControl();c.begin('请将扬声器输出设置到百分之三十','p')
        self.assertFalse(c.plan.requests)
        self.assertIsNone(c.validate_intent('self_audio_speaker_set_volume',{'volume':30}))

    def test_negative_does_not_block_other_clause(self):
        c=OperationControl();c.begin("打开摄像头，不要拍照", "p")
        self.assertIsNone(c.validate_intent("camera_open",{}))
        self.assertIsNotNone(c.validate_intent("self_camera_take_photo",{"question":"看看"}))


class ReceiptTests(unittest.TestCase):
    def test_no_functions_sentence_stream_and_fragmented_claim(self):
        from core.utils.operation_control import SpeechBuffer
        conn=SimpleNamespace(config={'operation_control':{'enabled':True}})
        stream=SpeechBuffer(conn)
        self.assertEqual(stream.feed('音量已'),[])
        self.assertEqual(stream.feed('调到30。下一句'),['这次没有确认到操作完成的回执，不能说已经完成。'])
        self.assertEqual(stream.feed('正常聊天。'),['下一句正常聊天。'])
        self.assertEqual(''.join(stream.delivered),'这次没有确认到操作完成的回执，不能说已经完成。下一句正常聊天。')

    def test_plain_json_fake_transport_never_spoken(self):
        from core.utils.operation_control import SpeechBuffer
        conn=SimpleNamespace(config={'operation_control':{'enabled':True}})
        stream=SpeechBuffer(conn)
        self.assertEqual(stream.feed('{"name":"self.volume",'),[])
        self.assertEqual(stream.feed('"arguments":{"volume":30}}'),[])
        self.assertEqual(stream.feed('',True),['这次没有发出有效的工具调用，操作没有执行。'])
    def test_volume_success_requires_matching_business_value(self):
        r=Request("volume",{"volume":30})
        for payload in ["true", "{}", '{"accepted":true}', '{"ok":true,"volume":50}', '{"ok":false,"volume":30}']:
            self.assertNotIn("已调到",feedback(r,ActionResponse(Action.REQLLM,result=payload)))
        self.assertEqual(feedback(r,ActionResponse(Action.REQLLM,result='{"ok":true,"volume":30}')),"音量已调到30。")

    def test_note_accepted_not_created(self):
        for raw in ['{"accepted":true}', 'true', '{"status":"created","id":-1}', 'error', '{"status":"created","id":1,"ok":false}']:
            with self.subTest(raw=raw), self.assertRaises(DeviceToolError):
                require_note_created(raw)
        require_note_created('已记录：测试')
        require_note_created('{"status":"created","id":1}')

    def test_false_business_ok_is_error(self):
        with self.assertRaises(DeviceToolError):
            unwrap_tool_result({"isError":False,"content":[{"type":"text","text":'{"ok":false,"message":"未保存"}'}]})

    def test_no_envelope_inference(self):
        for kind in ["preview_open","preview_close","note","reminder"]:
            self.assertNotIn("已打开",feedback(Request(kind),ActionResponse(Action.REQLLM,result='true')))

    def test_formatting_only_does_not_rewrite_personality(self):
        conn=SimpleNamespace(config={'operation_control':{'enabled':True}})
        self.assertEqual(guard_reply(conn,'[smirks]这话可没那么简单～😉'),'这话可没那么简单')
        self.assertEqual(guard_reply(conn,'[serious]我不赞同这个判断。'),'[serious]我不赞同这个判断。')


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn,self.manager,self.executor=fixture()
        self.face=patch("core.utils.face_enrollment_guard.maybe_intercept_face_enrollment_tool",return_value=None)
        self.reminder=patch("core.utils.device_reminder.maybe_intercept_reminder_tool",return_value=None)
        self.face.start();self.reminder.start()
    async def asyncTearDown(self):
        self.face.stop();self.reminder.stop()

    async def test_route_no_model_required(self):
        plan=get_control(self.conn).begin("把音量调到30","p")
        replies,results=await execute_plan(self.conn,plan)
        self.assertEqual(replies,["音量已调到30。"])
        self.assertEqual(self.executor.calls,[("self_audio_speaker_set_volume",{"volume":30})])
        self.assertFalse(results)

    async def test_relative_reads_fresh_status(self):
        plan=get_control(self.conn).begin("把音量调低十格","p")
        replies,_=await execute_plan(self.conn,plan)
        self.assertEqual(self.executor.calls,[('self_get_device_status',{}),('self_audio_speaker_set_volume',{'volume':40})])
        self.assertEqual(replies,["音量已调到40。"])

    async def test_relative_failure_does_not_write(self):
        self.executor.result=ActionResponse(Action.REQLLM,result='{"accepted":true}')
        plan=get_control(self.conn).begin("把音量调低十格","p")
        replies,_=await execute_plan(self.conn,plan)
        self.assertEqual(len(self.executor.calls),1)
        self.assertIn("没有调整",replies[0])

    async def test_two_relative_changes_read_status_each_time(self):
        plan=get_control(self.conn).begin('把音量调低10格，再把音量调低10格','p')
        await execute_plan(self.conn,plan)
        self.assertEqual([c[1].get('volume') for c in self.executor.calls if c[0]=='self_audio_speaker_set_volume'],[40,30])
        self.assertEqual(sum(c[0]=='self_get_device_status' for c in self.executor.calls),2)

    async def test_concept_question_repairs_once_without_device_call(self):
        control=get_control(self.conn);control.begin('音量是什么','p')
        result=await self.manager.execute_tool('self_get_device_status',{})
        self.assertEqual(result.action,Action.REQLLM)
        self.assertTrue(control.force_answer)
        self.assertFalse(self.executor.calls)
        second=await self.manager.execute_tool('self_get_device_status',{})
        self.assertEqual(second.action,Action.RESPONSE)
        self.assertFalse(self.executor.calls)

    async def test_invalid_schema_no_dispatch(self):
        for args in [{"volume":True},{},{"volume":"30"}]:
            result=await self.manager.execute_tool("self_audio_speaker_set_volume",args)
            self.assertEqual(result.action,Action.RESPONSE)
        self.assertFalse(self.executor.calls)

    async def test_firmware_brightness_minimum(self):
        plan=get_control(self.conn).begin("把亮度调到40","p")
        replies,_=await execute_plan(self.conn,plan)
        self.assertEqual(self.executor.calls, [('self_screen_set_brightness', {'brightness': 50})])
        self.assertIn("已调到50",replies[0])

    async def test_missing_preview_never_replaced_by_photo(self):
        del self.executor.tools["camera_open"]
        plan=get_control(self.conn).begin("打开摄像头","p")
        replies,_=await execute_plan(self.conn,plan)
        self.assertFalse(self.executor.calls)
        self.assertIn("不支持",replies[0])

    async def test_not_ready_or_closed_no_dispatch(self):
        self.conn.mcp_client.ready=False
        await self.manager.execute_tool("self_audio_speaker_set_volume",{"volume":30})
        self.assertFalse(self.executor.calls)
        self.conn.mcp_client.ready=True;self.conn.mcp_client.closed=True
        await self.manager.execute_tool("self_audio_speaker_set_volume",{"volume":30})
        self.assertFalse(self.executor.calls)

    async def test_unknown_name_no_repair_dispatch(self):
        await self.manager.execute_tool("selfcameratake_photo",{"question":"看看"})
        self.assertFalse(self.executor.calls)

    async def test_duplicate_parallel_dispatch_only_once(self):
        self.executor.delay=.01
        results=await asyncio.gather(*(self.manager.execute_tool("self_audio_speaker_set_volume",{"volume":30}) for _ in range(3)))
        self.assertEqual(len(self.executor.calls),1)
        self.assertEqual(results[0].response,"音量已调到30。")

    async def test_unknown_timeout_no_automatic_retry(self):
        self.executor.delay=.04
        with patch("core.providers.tools.unified_tool_manager.TOOL_EXECUTE_TIMEOUT",.005):
            a=await self.manager.execute_tool("self_audio_speaker_set_volume",{"volume":30})
            b=await self.manager.execute_tool("self_audio_speaker_set_volume",{"volume":30})
        self.assertEqual(len(self.executor.calls),1)
        self.assertIn("结果尚不确定",a.response)
        self.assertEqual(a.response,b.response)

    async def test_new_turn_reexecutes_new_authorized_request(self):
        for _ in range(2):
            get_control(self.conn).begin("把音量调到30","p")
            await self.manager.execute_tool("self_audio_speaker_set_volume",{"volume":30})
        self.assertEqual(len(self.executor.calls),2)

    async def test_changed_catalog_checked_again(self):
        self.manager.get_all_tools()
        del self.executor.tools['self_audio_speaker_set_volume']
        await self.manager.execute_tool('self_audio_speaker_set_volume',{'volume':30})
        self.assertFalse(self.executor.calls)

    async def test_rollback_flag_retains_old_executor(self):
        self.conn.config['operation_control']['enabled']=False
        await self.manager.execute_tool('self_audio_speaker_set_volume',{'volume':30})
        self.assertEqual(len(self.executor.calls),1)

    async def test_parameter_correction_only_after_confirmed_control(self):
        c=get_control(self.conn)
        await execute_plan(self.conn,c.begin('把音量调到30','p'))
        p=c.begin('改成四十','p')
        self.assertEqual(p.requests[0].arguments,{'volume':40})
        self.assertFalse(c.begin('改成50','other').requests)


if __name__ == '__main__':
    unittest.main()
