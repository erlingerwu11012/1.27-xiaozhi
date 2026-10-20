"""reminder_event 入站处理：含 interaction 生命周期（仅监听控制，不改提醒业务状态）。"""

from __future__ import annotations

import re
import time
from typing import Any, Dict

from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.utils.reminder_audit import audit_event, conn_ids
from core.utils.reminder_interaction import close_matching_interaction, open_interaction, renew_interaction

TAG = __name__

INSTANCE_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{3,128}$")
ALLOWED_EVENTS = frozenset(
    {
        "created",
        "scheduled",
        "due",
        "delivered",
        "played",
        "action",
        "failed",
        "cancelled",
        "interaction_opened",
        "interaction_closed",
        "interaction_renewed",
    }
)
INTERACTION_CLOSE_REASONS = frozenset(
    {"resolved", "timeout", "presence_lost", "preempted"}
)


class ReminderEventMessageHandler(TextMessageHandler):
    """reminder_event：审计 + interaction 监听生命周期控制。"""

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.REMINDER_EVENT

    async def handle(self, conn, msg_json: Dict[str, Any]) -> None:
        ids = conn_ids(conn)
        event = str(msg_json.get("event") or "").strip()
        instance_id = str(msg_json.get("instance_id") or "").strip()

        if event == "interaction_opened":
            if not INSTANCE_ID_RE.match(instance_id):
                audit_event(
                    "reminder_event_rejected",
                    **ids,
                    instance_id=instance_id,
                    result_code="invalid",
                    extra={"reason": "schema"},
                )
                return
            try:
                revision = int(msg_json.get("revision"))
            except (TypeError, ValueError):
                audit_event(
                    "reminder_event_rejected",
                    **ids,
                    instance_id=instance_id,
                    result_code="invalid",
                    extra={"reason": "interaction_schema"},
                )
                return
            if revision < 0:
                audit_event(
                    "reminder_event_rejected",
                    **ids,
                    instance_id=instance_id,
                    result_code="invalid",
                    extra={"reason": "interaction_schema"},
                )
                return
            opened, open_reason = open_interaction(
                conn,
                instance_id=instance_id,
                revision=revision,
                expires_at=msg_json.get("expires_at"),
            )
            if not opened:
                audit_event(
                    "reminder_event_rejected",
                    **ids,
                    instance_id=instance_id,
                    result_code="invalid",
                    extra={"reason": open_reason},
                )
                return
            from core.utils.reminder_interaction import get_interaction_state

            istate = get_interaction_state(conn)
            extra = {
                "expires_at": istate.expires_at,
                "received_at": istate.received_at,
            }
            if istate.expires_at_clipped:
                extra["expires_at_clipped"] = 1
            audit_event(
                "interaction_opened",
                **ids,
                instance_id=instance_id,
                revision=revision,
                result_code=open_reason if open_reason != "ok" else "ok",
                extra=extra,
            )
            return

        if event == "interaction_renewed":
            if not INSTANCE_ID_RE.fullmatch(instance_id): return
            accepted, reason = renew_interaction(conn, instance_id=instance_id,
                revision=msg_json.get("revision"), expires_at=msg_json.get("expires_at"))
            audit_event("interaction_renewed" if accepted else "reminder_event_rejected",
                **ids, instance_id=instance_id, revision=msg_json.get("revision"), result_code=reason)
            return

        if event == "interaction_closed":
            reason = str(msg_json.get("reason") or "").strip()
            if reason not in INTERACTION_CLOSE_REASONS:
                audit_event(
                    "reminder_event_rejected",
                    **ids,
                    instance_id=instance_id,
                    result_code="invalid",
                    extra={"reason": "interaction_close_reason"},
                )
                return
            if not close_matching_interaction(conn, instance_id=instance_id,
                    revision=msg_json.get("revision"), reason=reason):
                audit_event("reminder_event_rejected", **ids, instance_id=instance_id,
                    result_code="window_mismatch")
                return
            audit_event(
                "interaction_closed",
                **ids,
                instance_id=instance_id,
                result_code=reason,
            )
            return

        if event not in ALLOWED_EVENTS or not INSTANCE_ID_RE.match(instance_id):
            audit_event(
                "reminder_event_rejected",
                **ids,
                instance_id=instance_id,
                result_code="invalid",
                extra={"reason": "schema"},
            )
            return
        audit_event(
            "reminder_event_received",
            **ids,
            instance_id=instance_id,
            revision=msg_json.get("revision"),
            voice_revision=msg_json.get("voice_revision"),
            creator_person_id=str(msg_json.get("creator_person_id") or ""),
            recipient_person_id=str(msg_json.get("recipient_person_id") or ""),
            result_code=str(msg_json.get("result_code") or "ok"),
            extra={"phase": event},
        )
