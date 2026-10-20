"""Private protocol. It is never exposed as a language model function."""
import asyncio
import copy


async def private_rpc(conn, method, params, timeout=5):
    from core.providers.tools.device_mcp.mcp_handler import connection_mcp, send_mcp_message
    client = connection_mcp(conn)
    request_id = await client.get_next_id()
    future = asyncio.get_running_loop().create_future()
    await client.register_call_result_future(request_id, future)
    try:
        await send_mcp_message(conn, {"jsonrpc":"2.0", "id":request_id,
                                   "method":method, "params":params})
        return await asyncio.wait_for(future, timeout)
    finally:
        await client.cleanup_call_result(request_id)


def schedule_directory_sync(conn, state):
    client = getattr(conn, "mcp_client", None)
    caps = getattr(client, "capabilities", {}).get("experimental", {})
    if not isinstance(caps, dict) or caps.get("personalIdentity", 0) < 2:
        return
    version = state.get("directory_version")
    if getattr(conn, "identity_synced_version", None) == version:
        return
    conn.identity_synced_version = None
    pending = getattr(conn, "identity_sync_task", None)
    if pending and not pending.done():
        return
    snapshot = copy.deepcopy(state)
    snapshot["account_id"] = str(snapshot.get("account_id") or "")
    async def synchronize():
        from config.manage_api_client import ManageApiClient
        try:
            result = await private_rpc(conn, "identity/sync", snapshot)
            if not isinstance(result, dict) or result.get("ok") is not True or result.get("directory_version") != version:
                return
            client = ManageApiClient(conn.config)
            tasks = {item["id"]:item for item in snapshot.get("cleanup_tasks", [])}
            from core.utils.person_material_outbox import material_outbox
            for cleanup_id in result.get("acknowledged", []):
                task = tasks.get(cleanup_id)
                if not task:
                    continue
                await asyncio.to_thread(material_outbox.retire, snapshot["account_id"], task["user_id"], task["generation"])
                from core.utils.person_short_memory import retire
                await asyncio.to_thread(retire,snapshot["account_id"],task["user_id"],task["generation"])
                if task["generation"] > 0:
                    from core.utils.person_short_memory import retire_legacy_agents
                    await asyncio.to_thread(retire_legacy_agents, snapshot.get("agent_ids", []))
                histories = getattr(conn, "_person_dialogues", {})
                for key in list(histories):
                    if key[0] == snapshot["account_id"] and key[1] == task["user_id"]:
                        histories[key].invalidate_summary()
                        del histories[key]
                memory = getattr(conn, "memory", None)
                if hasattr(memory, "_portraits"):
                    memory._portraits.clear()
                if hasattr(memory, "_queries"):
                    memory._queries.clear()
                await client.request("POST", "user-identities/internal/cleanup-ack",
                    json={"accountId":snapshot["account_id"], "deviceId":conn.device_id,
                          "cleanupId":cleanup_id}, timeout=2)
            if getattr(conn, "identity_state", {}).get("directory_version") == version:
                conn.identity_synced_version = version
        except Exception:
            # Absence of an acknowledgement is not a successful cleanup.
            conn.identity_synced_version = None
    conn.identity_sync_task = asyncio.create_task(synchronize())


async def report_capability(conn, result):
    from config.manage_api_client import ManageApiClient
    from core.utils.person_identity import refresh_directory
    caps = result.get("capabilities", {}).get("experimental", {})
    if not isinstance(caps, dict):
        caps = {}
    versions = {name:int(caps.get(name, 0)) for name in
                ("personalIdentity", "identityCleanup", "personBehavior", "weeklySchedule")
                if isinstance(caps.get(name, 0), int) and not isinstance(caps.get(name, 0), bool)}
    account = str((conn.config or {}).get("sys_user_id") or "")
    if not account:
        conn.logger.bind(tag=__name__).warning("[person_identity] capability_report_skipped account_missing")
        return
    try:
        await ManageApiClient(conn.config).request("POST", "user-identities/internal/capability",
            json={"accountId":account, "deviceId":conn.device_id, "versions":versions,
                  "firmwareVersion":str(result.get("serverInfo", {}).get("version", ""))[:64]}, timeout=2)
        await refresh_directory(conn)
        from core.utils.person_maintenance import start_maintenance
        start_maintenance(conn)
    except Exception as exc:
        conn.logger.bind(tag=__name__).warning(
            f"[person_identity] capability_report_failed error_type={type(exc).__name__}"
        )
        conn.identity_synced_version = None
