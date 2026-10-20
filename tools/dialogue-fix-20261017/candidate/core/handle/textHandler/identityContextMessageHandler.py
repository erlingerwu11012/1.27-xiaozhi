"""identity_context 入站处理：只接受设备上报的在场用户，不覆盖声纹说话用户。"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional

from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType

USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def _bound_present_user(conn, value: Any) -> Optional[Dict[str, str]]:
    """只接受本连接配置中已显式绑定的人脸/用户，显示名永远以服务端配置为准。"""
    if not isinstance(value, dict):
        return None
    user_id = str(value.get("user_id") or value.get("userId") or "").strip()
    face_profile_id = str(
        value.get("face_profile_id") or value.get("faceProfileId") or ""
    ).strip()
    if user_id and not USER_ID_RE.match(user_id):
        return None

    bindings = (getattr(conn, "config", None) or {}).get("face_identity_bindings")
    if not isinstance(bindings, list):
        return None
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        bound_user_id = str(
            binding.get("user_id") or binding.get("userId") or ""
        ).strip()
        bound_profile_id = str(
            binding.get("face_profile_id") or binding.get("faceProfileId") or ""
        ).strip()
        display_name = str(
            binding.get("display_name") or binding.get("displayName") or ""
        ).strip()
        if not bound_user_id or not display_name:
            continue
        matches_user = bool(user_id) and user_id == bound_user_id
        matches_face = bool(face_profile_id) and face_profile_id == bound_profile_id
        if matches_user or matches_face:
            if user_id and user_id != bound_user_id:
                return None
            if face_profile_id and face_profile_id != bound_profile_id:
                return None
            return {"user_id": bound_user_id, "display_name": display_name}
    return None


class IdentityContextMessageHandler(TextMessageHandler):
    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.IDENTITY_CONTEXT

    async def handle(self, conn, msg_json: Dict[str, Any]) -> None:
        # 仅处理 future firmware 的 current_present_user；speaker 是服务端下行字段，
        # 即使设备回显也绝不写入，保证 face/speaker 上下文互不覆盖。
        if "current_present_user" not in msg_json:
            return
        value = msg_json.get("current_present_user")
        if value is None:
            conn.current_present_user = None
            conn.current_present_user_seen_at = 0.0
            return
        present = _bound_present_user(conn, value)
        if present is None:
            conn.logger.warning("[identity_context] reject invalid or unbound present user")
            return
        conn.current_present_user = present
        conn.current_present_user_seen_at = time.monotonic()
        conn.logger.info("[identity_context] present_user_updated")
