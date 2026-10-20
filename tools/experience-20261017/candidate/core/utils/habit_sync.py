"""Private persisted habit synchronization; not a language model tool."""
import asyncio
from weakref import WeakValueDictionary

_locks = WeakValueDictionary()
ALLOWED_ERRORS = {"identity_mismatch", "invalid_config", "hash_mismatch", "quota_exceeded",
                  "storage_full", "storage_error", "legacy_ambiguous"}


def verified_receipt(result, payload):
    return (isinstance(result, dict) and result.get("ok") is True and result.get("persisted") is True
            and result.get("sync_id") == payload["sync_id"]
            and result.get("content_hash") == payload["content_hash"]
            and result.get("enabled") is payload["enabled"]
            and type(result.get("device_rule_id")) is int
            and result["device_rule_id"] >= (1 if payload["enabled"] else 0))


async def synchronize_habit(config, server, habit_id):
    from config.manage_api_client import ManageApiClient
    from core.utils.device_outbound import is_outbound_allowed
    from core.utils.person_directory_sync import private_rpc
    from core.utils.person_identity import refresh_directory
    lock = _locks.setdefault(habit_id, asyncio.Lock())
    async with lock:
        api = ManageApiClient(config)
        record = await api.request("GET", f"habits/internal/{habit_id}", timeout=5)
        if not isinstance(record, dict) or record.get("ok") is not True:
            return {"ok": False, "error": (record or {}).get("error", "invalid_record")}
        payload = dict(record["payload"])
        device = record["device_id"]
        session = server.get_current_main_session_id(device) if server else None
        conn = (getattr(server, "_connections", {}).get(device) or {}).get(session)
        error, state, result = "device_offline", "pending", None
        if conn and is_outbound_allowed(conn):
            if str((conn.config or {}).get("sys_user_id") or "") != payload["account_id"]:
                error, state = "ownership_mismatch", "failed"
            else:
                caps = getattr(getattr(conn, "mcp_client", None), "capabilities", {}).get("experimental", {})
                if type(caps.get("habitSync")) is not int or caps["habitSync"] < 1:
                    error, state = "firmware_unsupported", "upgrade_required"
                else:
                    directory = await refresh_directory(conn)
                    task = getattr(conn, "identity_sync_task", None)
                    if task:
                        try: await asyncio.wait_for(asyncio.shield(task), 6)
                        except asyncio.TimeoutError: pass
                    version = directory.get("directory_version") if isinstance(directory, dict) else None
                    if (not version or getattr(conn, "identity_synced_version", None) != version or
                        str(directory.get("account_id")) != payload["account_id"]):
                        error, state = "directory_not_ready", "pending"
                    else:
                        payload["directory_version"] = version
                        try:
                            result = await private_rpc(conn, "habit/sync", payload, timeout=8)
                            if not is_outbound_allowed(conn) or conn.session_id != session:
                                error, state = "connection_closed", "pending"
                            elif verified_receipt(result, payload):
                                error, state = None, "synced"
                            else:
                                code = result.get("error") if isinstance(result, dict) else None
                                error, state = code if code in ALLOWED_ERRORS else "invalid_receipt", "failed"
                        except asyncio.TimeoutError:
                            # Retry the same source key/hash to reconcile a lost persisted acknowledgement.
                            error, state = "receipt_timeout", "pending"
                        except Exception:
                            error, state = "connection_closed", "pending"
        ack = await api.request("POST", "habits/internal/ack", timeout=5, json={
            "habitId": habit_id, "contentHash": payload["content_hash"],
            "configVersion": record["config_version"], "state": state, "error": error,
            "deviceRuleId": result["device_rule_id"] if state == "synced" else None})
        if not isinstance(ack, dict) or ack.get("accepted") is not True:
            return {"ok": False, "error": "configuration_changed", "sync_state": "pending"}
        return {"ok": state == "synced", "error": error, "sync_state": state,
                "sync_id": payload["sync_id"], "content_hash": payload["content_hash"],
                "device_rule_id": result["device_rule_id"] if state == "synced" else None}
