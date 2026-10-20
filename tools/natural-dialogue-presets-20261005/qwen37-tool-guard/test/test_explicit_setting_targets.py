"""Regression for real model clamping an out-of-range explicit request."""
import asyncio
import unittest
from test_operation_control import fixture
from core.utils.operation_control import get_control

class ExplicitTargetTests(unittest.TestCase):
    def dispatch(self, user, name, args):
        conn,manager,executor=fixture()
        get_control(conn).begin(user,('test','actor'))
        reply=asyncio.run(manager.execute_tool(name,args))
        return executor.calls,reply

    def test_out_of_range_volume_with_extra_clause_cannot_be_clamped(self):
        calls,reply=self.dispatch('把音量设置为120，直接调。','self_audio_speaker_set_volume',{'volume':100})
        self.assertEqual(calls,[])
        self.assertIn('目标不一致',reply.response)

    def test_out_of_range_brightness_with_extra_clause_cannot_be_clamped(self):
        calls,_=self.dispatch('屏幕亮度设成20，帮我设置。','self_screen_set_brightness',{'brightness':50})
        self.assertEqual(calls,[])

    def test_valid_literal_target_with_extra_clause_executes_once(self):
        calls,_=self.dispatch('把音量设置为30，直接调。','self_audio_speaker_set_volume',{'volume':30})
        self.assertEqual(calls,[('self_audio_speaker_set_volume',{'volume':30})])

    def test_valid_target_cannot_be_substituted(self):
        calls,_=self.dispatch('屏幕亮度设成80，帮我设置。','self_screen_set_brightness',{'brightness':70})
        self.assertEqual(calls,[])

    def test_quoted_or_negated_setting_never_executes(self):
        for user in ['他说“把音量设成30”，这是什么意思？','不要把音量设成30，先解释一下。']:
            calls,_=self.dispatch(user,'self_audio_speaker_set_volume',{'volume':30})
            self.assertEqual(calls,[])

    def test_relative_adjustment_still_allows_status_read(self):
        calls,_=self.dispatch('把音量调低10格','self_get_device_status',{})
        self.assertEqual(calls,[('self_get_device_status',{})])

    def test_known_multi_action_targets_remain_valid(self):
        calls,_=self.dispatch('音量设成30，亮度设成80','self_screen_set_brightness',{'brightness':80})
        self.assertEqual(calls,[('self_screen_set_brightness',{'brightness':80})])

if __name__=='__main__':unittest.main()
