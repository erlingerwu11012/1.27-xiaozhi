"""Quiet background retries and person behavior analysis; no synthetic chat turn."""
import asyncio
import uuid
import json
import time
from dataclasses import replace
from contextvars import ContextVar
from core.utils.person_identity import PersonTurn, activate, deactivate

service_control = ContextVar("person_service_control", default=False)


async def replay_behavior(conn, actor):
    """Recover a device append whose original MCP response was lost."""
    from core.utils.person_directory_sync import private_rpc
    from core.utils.person_material_outbox import material_outbox
    cursor = "0"
    # A 24 KB device log fits in these bounded pages; all pages precede analysis.
    for _ in range(40):
        page = await private_rpc(conn, "behavior/export", {"actor":actor.payload(), "after":cursor})
        if not isinstance(page, dict) or not isinstance(page.get("records"), list):
            raise ValueError("invalid_behavior_page")
        for record in page["records"]:
            if (record.get("person") != actor.person_id
                    or str(record.get("account")) != actor.account_id
                    or int(record.get("generation", -1)) != actor.generation):
                raise ValueError("behavior_owner_mismatch")
            turn = str(record.get("turn") or "")
            event = str(record.get("event") or "")
            if not turn or len(turn) > 64 or not event:
                raise ValueError("invalid_behavior_event")
            original = replace(actor, turn_id=turn,
                directory_version=int(record.get("directory_version", 0)),
                voiceprint_id=str(record.get("voiceprint_id") or ""),
                template_version=int(record.get("template_version", 0)))
            material_outbox.enqueue(original,"behavior",json.dumps(record,ensure_ascii=False),event)
        next_cursor = str(page.get("cursor") or "")
        if not next_cursor.isdecimal() or int(next_cursor) < int(cursor):
            raise ValueError("invalid_behavior_cursor")
        await material_outbox.pump(conn)
        if not page.get("more"):
            return
        if int(next_cursor) <= int(cursor):
            raise ValueError("behavior_cursor_not_advancing")
        cursor = next_cursor
    raise ValueError("behavior_page_budget_exhausted")


async def acknowledge_device(conn, actor, result):
    from core.providers.tools.device_mcp.mcp_handler import call_mcp_tool
    rows = result.get("device_watermarks", []) if isinstance(result, dict) else []
    mark = next((str(row.get("watermark") or "") for row in rows
                 if row.get("device_id") == actor.device_id), "")
    if not mark.isdecimal() or int(mark) <= 0:
        return
    token = activate(conn, actor)
    control = service_control.set(True)
    try:
        await call_mcp_tool(conn, conn.mcp_client, "behavior.ack", {"watermark":mark}, timeout=5)
    finally:
        service_control.reset(control)
        deactivate(token)


async def maintain(conn):
    from config.manage_api_client import ManageApiClient
    from core.utils.person_directory_sync import normalize_directory, schedule_directory_sync
    from core.utils.person_material_outbox import material_outbox
    from core.utils.habit_router import route_habit_analysis
    client = ManageApiClient(conn.config)
    try:
        while not getattr(conn, "stop_event", None) or not conn.stop_event.is_set():
            await material_outbox.pump(conn)
            account = str((conn.config or {}).get("sys_user_id") or "")
            caps = getattr(getattr(conn,"mcp_client",None),"capabilities",{}).get("experimental",{})
            if account and caps.get("personBehavior",0) >= 2:
                try:
                    state = await client.request("GET", f"user-identities/internal/state/{account}", timeout=2)
                    if str(state.get("account_id")) != account:
                        raise ValueError("account_changed")
                    state = normalize_directory(state)
                    conn.identity_state = state
                    schedule_directory_sync(conn, state)
                    if getattr(conn,"identity_synced_version",None) == state.get("directory_version"):
                        profiles = state.get("voice_profiles", []) if state.get("mode") == "personal" else []
                        if state.get("mode") == "default" and state.get("default_user_id"):
                            profiles = [{"user_id":state["default_user_id"], "display_name":"默认用户"}]
                        seen = set()
                        for profile in profiles:
                            person = profile["user_id"]
                            if person in seen:
                                continue
                            seen.add(person)
                            actor = PersonTurn(account,person,
                                int(state.get("default_generation",0)) if state["mode"] == "default" else 0,
                                int(state["directory_version"]),state["mode"],
                                "default" if state["mode"] == "default" else "matched",
                                "maintenance_"+uuid.uuid4().hex,conn.device_id,
                                str(conn.config.get("agent_id") or conn.config.get("agentId") or getattr(conn,"agent_id","") or ""),0,
                                str(profile.get("voiceprint_id") or ""),int(profile.get("template_version") or 0),
                                str(profile.get("display_name") or ""))
                            await replay_behavior(conn,actor)
                            ack = await client.request("POST","person-memory/internal/behavior/acknowledgements",json=actor.payload(),timeout=2)
                            await acknowledge_device(conn,actor,ack)
                            job = await client.request("POST","person-memory/internal/behavior/prepare",json=actor.payload(),timeout=2)
                            if job.get("status") == "ready":
                                completed = await asyncio.to_thread(route_habit_analysis,conn,job,actor)
                                conn.logger.bind(tag=__name__).info(
                                    f"[maintenance] habit_analysis status={'complete' if completed else 'deferred'} person={person}")
                except Exception as exc:
                    # Throttle diagnostics; retain durable work without speaking.
                    if time.monotonic() >= getattr(conn,"_maintenance_error_after",0):
                        conn._maintenance_error_after = time.monotonic()+300
                        conn.logger.bind(tag=__name__).warning(
                            f"[maintenance] deferred error_type={type(exc).__name__}")
            await asyncio.sleep(30)
    except asyncio.CancelledError:
        pass


def start_maintenance(conn):
    prior = getattr(conn,"person_maintenance_task",None)
    if not prior or prior.done():
        conn.person_maintenance_task = asyncio.create_task(maintain(conn))
