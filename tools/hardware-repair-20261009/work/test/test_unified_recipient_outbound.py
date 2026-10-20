"""设备出站收件人字段：不得向旧固件下发 recipient_user_id。"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils.recipient_resolver import (
    RecipientResolution,
    RecipientResultCode,
    apply_recipient_to_device_args,
)
from core.utils.unified_recipient_resolver import apply_unified_recipient_to_device_args


def _ok_all() -> RecipientResolution:
    return RecipientResolution(
        code=RecipientResultCode.ALL,
        selector_type="all",
        recipient_person_id="all",
        recipient_display_name="所有人",
        attach_to_device=True,
    )


def _ok_usr() -> RecipientResolution:
    return RecipientResolution(
        code=RecipientResultCode.RESOLVED,
        selector_type="user_id",
        recipient_person_id="usr_aabb12",
        recipient_display_name="小明",
        attach_to_device=True,
    )


class UnifiedOutboundRecipientTests(unittest.TestCase):
    def test_all_uses_person_id_only(self):
        args = apply_unified_recipient_to_device_args(
            {"text": "喝水", "recipient_user_id": "should_strip"},
            _ok_all(),
        )
        self.assertEqual(args.get("recipient_person_id"), "all")
        self.assertEqual(args.get("recipient_display_name"), "所有人")
        self.assertNotIn("recipient_user_id", args)
        self.assertNotIn("creator_person_id", args)

    def test_usr_uses_person_id_only(self):
        args = apply_unified_recipient_to_device_args(
            {"text": "吃药", "recipient_user_id": "usr_leak"},
            _ok_usr(),
        )
        self.assertEqual(args.get("recipient_person_id"), "usr_aabb12")
        self.assertEqual(args.get("recipient_display_name"), "小明")
        self.assertNotIn("recipient_user_id", args)

    def test_legacy_apply_also_strips_user_id(self):
        args = apply_recipient_to_device_args(
            {"text": "x", "recipient_user_id": "usr_leak"},
            _ok_usr(),
        )
        self.assertEqual(args.get("recipient_person_id"), "usr_aabb12")
        self.assertNotIn("recipient_user_id", args)


if __name__ == "__main__":
    unittest.main()
