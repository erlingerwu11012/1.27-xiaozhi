"""Reproduce a real primary-model response with no native photo call."""
import asyncio
import unittest
from test_operation_control import fixture
from core.utils.operation_control import get_control, execute_plan
from core.utils.operation_control import parse_request

class MissingNativeTimeCallTests(unittest.TestCase):
    def test_explicit_world_time_routes_to_real_tool_not_model_promise(self):
        for text,zone in [('请查询东京现在的时间','Asia/Tokyo'),('请查询伦敦现在的时间','Europe/London'),('请查询上海现在的时间','Asia/Shanghai'),('帮我查一下纽约现在几点','America/New_York')]:
            request=parse_request(text)
            self.assertEqual((request.kind,request.arguments),('world_time',{'timezone':zone}))

    def test_time_quote_negation_unknown_city_and_historical_date_stay_outside_fast_path(self):
        for text in ['不要查询东京现在的时间','他说“东京现在几点”是什么意思','查询美国现在的时间','查询东京明天九点对应的北京时间']:
            self.assertIsNone(parse_request(text))

    def test_missing_world_time_capability_is_reported_without_a_substitute(self):
        conn, manager, executor=fixture()
        plan=get_control(conn).begin('东京现在几点',('synthetic','actor'))
        messages,results=asyncio.run(execute_plan(conn,plan))
        self.assertIn('不支持世界时间查询',''.join(messages))
        self.assertEqual((executor.calls,results),([],[]))

    def test_known_mixed_queries_preserve_both_actions_and_exact_timezone(self):
        conn, manager, executor=fixture()
        plan=get_control(conn).begin('把音量调到30，然后查询东京时间',('synthetic','actor'))
        self.assertEqual([(r.kind,r.arguments) for r in plan.requests],[('volume',{'volume':30}),('world_time',{'timezone':'Asia/Tokyo'})])

class MissingNativePhotoCallTests(unittest.TestCase):
    def test_explicit_colloquial_photo_executes_before_model_prose(self):
        conn, manager, executor = fixture()
        plan = get_control(conn).begin('替我拍一张，看看眼前这个杯子', ('synthetic','actor'))
        self.assertEqual(len(plan.requests),1)
        asyncio.run(execute_plan(conn, plan))
        self.assertEqual(executor.calls,[('self_camera_take_photo',{'question':'看看眼前这个杯子'})])

    def test_same_phrase_in_negation_or_quote_never_executes(self):
        for text in ['不要替我拍一张，看看眼前这个杯子','他说“替我拍一张，看看眼前这个杯子”是什么意思？']:
            conn, manager, executor = fixture()
            control=get_control(conn)
            plan=control.begin(text, ('synthetic','actor'))
            self.assertFalse(plan.requests)
            self.assertIsNotNone(control.validate_intent('self_camera_take_photo',{'question':'杯子'}))
            self.assertEqual(executor.calls,[])

if __name__=='__main__': unittest.main()
