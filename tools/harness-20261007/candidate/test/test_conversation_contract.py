import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.providers.llm.openai.openai import LLMProvider
from core.utils.hardware_billing import provider_context


class NativeModelContractTests(unittest.TestCase):
    def test_qwen38_chat_and_tools_share_non_thinking_contract(self):
        tools = [{'type': 'function', 'function': {'name': 'read_status', 'parameters': {'type': 'object'}}}]
        for model in ('qwen3.8-flash', 'qwen3.8-max'):
            for hardware in (False, True):
                with self.subTest(model=model, hardware=hardware):
                    provider = LLMProvider({'model_name': model, 'api_key': 'sk-test-not-real', 'base_url': 'http://127.0.0.1:9/v1',
                        'hardware_billing': hardware, 'hardware_account_id': '123', 'hardware_operation': 'llm'})
                    create = MagicMock(side_effect=lambda **kwargs: iter([]))
                    provider._create_with_retry = create
                    messages = [{'role': 'system', 'content': 'test'}, {'role': 'user', 'content': 'test'}]
                    list(provider.response('test', messages))
                    list(provider.response_with_functions('test', messages, tools))
                    self.assertEqual(create.call_count, 2)
                    for call in create.call_args_list:
                        self.assertEqual(call.kwargs['extra_body'], {'enable_thinking': False, 'preserve_thinking': False})
                        self.assertEqual(call.kwargs['model'], model)
                    self.assertEqual(create.call_args.kwargs['tools'], tools)
                    self.assertLessEqual(provider.input_limit_tokens, 991808)
                    provider.client.close()

    def test_new_text_models_cannot_be_billed_as_vision_or_untrusted_alias(self):
        for model, operation in [('qwen3.8-flash', 'vision'), ('qwen3.8-max', 'tts'), ('qwen3.8-flash-unverified', 'llm')]:
            with self.assertRaises(ValueError):
                provider_context({'hardware_billing': True, 'hardware_account_id': '123', 'model_name': model, 'hardware_operation': operation})


if __name__ == '__main__':
    unittest.main()
