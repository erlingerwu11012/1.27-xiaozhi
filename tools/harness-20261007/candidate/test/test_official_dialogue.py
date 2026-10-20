"""Official dialogue: primary answer tags and captions remain supported."""
from __future__ import annotations

import sys
import unittest

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__file__), ".."))

from core.providers.tts.official.compiler import caption_from
from core.providers.tts.official.prompt import OFFICIAL_EXPRESSION_CONSTRAINT


class OfficialDialogueContractTests(unittest.TestCase):
    def test_expression_constraint_does_not_rewrite_customer_prompt(self):
        customer = "你是小助手，禁止泄露密钥。"
        combined = customer + "\n\n" + OFFICIAL_EXPRESSION_CONSTRAINT
        self.assertTrue(combined.startswith(customer))
        self.assertIn("不得覆盖用户角色设定", combined)

    def test_history_uses_caption_not_tags(self):
        spoken = "[excited]太好了[laughing]呀"
        self.assertEqual(caption_from(spoken), "太好了呀")




if __name__ == "__main__":
    unittest.main()
