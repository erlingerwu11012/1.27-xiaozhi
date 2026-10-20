"""Actor-bound local archive lookup, then optional paid cloud fallback."""
import asyncio
from core.utils.person_identity import current_turn


async def search(conn, query):
    actor = current_turn(conn)
    if not actor or not actor.eligible:
        return {"status": "identity_unknown", "text": ""}
    if not isinstance(query, str) or not query.strip() or len(query) > 2048:
        return {"status": "invalid_query", "text": ""}
    from config.manage_api_client import ManageApiClient
    try:
        local = await ManageApiClient(conn.config).request("POST", "person-memory/internal/recent",
                    json={"actor": actor.payload(), "query": query}, timeout=1)
    except Exception:
        local = {"text": "", "status": "temporarily_unavailable"}
    # Explicit suppression or stale authority must not fall through to cloud.
    if local.get("status") in {"suppressed", "identity_stale"}:
        return {**local, "text": str(local.get("text") or "")[:3000], "source": "local"}
    if local.get("reliable") and local.get("text"):
        return {**local,"text":str(local["text"])[:3000],"source":"local"}
    provider=getattr(conn,"memory",None)
    if getattr(provider,"personal",False) and actor.cloud_eligible:
        cloud=await provider.search(conn,query)
        return {**cloud,"text":str(cloud.get("text") or "")[:1500],"source":"cloud"}
    return {"status":"not_found","text":"","source":"local"}


async def override(conn, action, match, replacement=None):
    actor=current_turn(conn)
    if not actor or not actor.eligible:return {"status":"identity_unknown"}
    provider=getattr(conn,"memory",None)
    if getattr(provider,"personal",False) and actor.cloud_eligible:
        return await provider.override(conn,action,match,replacement)
    from config.manage_api_client import ManageApiClient
    await ManageApiClient(conn.config).request("POST","person-memory/internal/override",
        json={"actor":actor.payload(),"action":action,"match":match,"replacement":replacement},timeout=3)
    from core.utils.person_short_memory import invalidate
    invalidate(actor)
    conn.dialogue.invalidate_summary()
    conn.dialogue.dialogue[:]=[m for m in conn.dialogue.dialogue if m.role=="system"]
    if provider:provider.short_memory=""
    return {"status":"accepted","cloud_sync":"disabled"}
