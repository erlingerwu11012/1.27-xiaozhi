from pathlib import Path
root=Path(__file__).parent/'candidate'
def edit(rel,old,new):
 p=root/rel;s=p.read_text(encoding='utf-8');assert old in s,rel;p.write_text(s.replace(old,new),encoding='utf-8')
py='main/xiaozhi-server/'
edit(py+'core/utils/reminder_interaction.py','    active: bool = False','    generation: int = 0\n    active: bool = False')
edit(py+'core/utils/reminder_interaction.py','        self.active = False','        self.generation += 1\n        self.active = False')
edit(py+'core/utils/reminder_interaction.py','    try:\n        exp = int(expires_at)','    if isinstance(expires_at, bool) or not isinstance(expires_at, int):\n        return False, "bad_expires_at", 0, False\n    try:\n        exp = int(expires_at)')
edit(py+'core/utils/reminder_interaction.py','async def _interaction_expire_worker(conn) -> None:', 'async def _interaction_expire_worker(conn, generation=None) -> None:')
edit(py+'core/utils/reminder_interaction.py','    expires_at = int(state.expires_at or 0)','    generation = state.generation if generation is None else generation\n    expires_at = int(state.expires_at or 0)\n    instance_id, revision = state.instance_id, state.revision')
edit(py+'core/utils/reminder_interaction.py','    if not state.active:\n        return\n    if int(time.time()) >= expires_at:', '    if not state.active or state.generation != generation or state.expires_at != expires_at:\n        return\n    if int(time.time()) >= expires_at:')
edit(py+'core/utils/reminder_interaction.py','                instance_id=state.instance_id,\n                revision=state.revision,','                instance_id=instance_id,\n                revision=revision,')
edit(py+'core/utils/reminder_interaction.py','loop.create_task(_interaction_expire_worker(conn))','loop.create_task(_interaction_expire_worker(conn, get_interaction_state(conn).generation))')
edit(py+'core/utils/reminder_interaction.py','    state.active = True','    state.generation += 1\n    state.active = True')
p=root/py/'core/utils/reminder_interaction.py'
with p.open('a',encoding='utf-8') as f:f.write('''

def renew_interaction(conn, *, instance_id, revision, expires_at):
    from core.utils.device_outbound import is_outbound_allowed
    if not is_outbound_allowed(conn):
        return False, "connection_closed"
    if not is_interaction_active(conn):
        return False, "interaction_closed"
    state = get_interaction_state(conn)
    if isinstance(revision, bool) or not isinstance(revision, int) or state.instance_id != instance_id or state.revision != revision:
        return False, "window_mismatch"
    received_at = int(time.time())
    ok, reason, exp, clipped = validate_interaction_expires_at(expires_at, received_at=received_at)
    if not ok: return False, reason
    if exp <= state.expires_at: return True, "unchanged"
    state.generation += 1
    state.received_at, state.expires_at, state.expires_at_clipped = received_at, exp, clipped
    _schedule_expire_task(conn)
    return True, "expires_at_clipped" if clipped else "ok"


def close_matching_interaction(conn, *, instance_id, revision, reason):
    state = get_interaction_state(conn)
    if isinstance(revision, bool) or not isinstance(revision, int) or not state.active or state.instance_id != instance_id or state.revision != revision:
        return False
    close_interaction(conn, reason=reason)
    return True
''')
edit(py+'core/handle/textHandler/reminderEventMessageHandler.py','from core.utils.reminder_interaction import close_interaction, open_interaction','from core.utils.reminder_interaction import close_matching_interaction, open_interaction, renew_interaction')
edit(py+'core/handle/textHandler/reminderEventMessageHandler.py','        "interaction_closed",\n    }','        "interaction_closed",\n        "interaction_renewed",\n    }')
edit(py+'core/handle/textHandler/reminderEventMessageHandler.py','        if event == "interaction_closed":','''        if event == "interaction_renewed":
            if not INSTANCE_ID_RE.fullmatch(instance_id): return
            accepted, reason = renew_interaction(conn, instance_id=instance_id,
                revision=msg_json.get("revision"), expires_at=msg_json.get("expires_at"))
            audit_event("interaction_renewed" if accepted else "reminder_event_rejected",
                **ids, instance_id=instance_id, revision=msg_json.get("revision"), result_code=reason)
            return

        if event == "interaction_closed":''')
edit(py+'core/handle/textHandler/reminderEventMessageHandler.py','            close_interaction(conn, reason=reason)','''            if not close_matching_interaction(conn, instance_id=instance_id,
                    revision=msg_json.get("revision"), reason=reason):
                audit_event("reminder_event_rejected", **ids, instance_id=instance_id,
                    result_code="window_mismatch")
                return''')
# Private capability only; never registered as a language-model tool.
p=Path('main/mcp_server.cc');s=p.read_text(encoding='utf-8');s=s.replace('\\"weeklySchedule\\":2','\\"weeklySchedule\\":2,\\"habitSync\\":1');p.write_text(s,encoding='utf-8')
