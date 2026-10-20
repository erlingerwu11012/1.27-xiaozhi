"""Daily managed facts. Query is exposed only through an explicit model tool."""
import asyncio
import json
import time
from collections import OrderedDict
from ..base import MemoryProviderBase
from core.utils.person_identity import current_turn


class MemoryProvider(MemoryProviderBase):
    personal = True

    def __init__(self, config, summary_memory=None):
        super().__init__(config)
        self._queries = OrderedDict()
        self._portraits = {}

    async def query_memory(self, query):
        # ConnectionHandler must never do automatic Search for this provider.
        return ""

    async def save_memory(self, msgs):
        # No device/agent transcript is uploaded on disconnect; turns are stamped at ingress.
        return None

    def record_turn(self, conn, actor, text):
        if not actor.cloud_eligible:
            return
        from core.utils.person_material_outbox import material_outbox
        try:
            parsed = json.loads(text) if isinstance(text,str) and text.lstrip().startswith("{") else None
            if isinstance(parsed,dict) and isinstance(parsed.get("content"),str):
                text=parsed["content"]
        except (ValueError,TypeError):
            pass
        material_outbox.enqueue(actor,"dialogue",str(text),actor.turn_id+":user")
        asyncio.run_coroutine_threadsafe(material_outbox.pump(conn),conn.loop)

    async def search(self, conn, query):
        actor=current_turn(conn)
        if actor is None or not actor.cloud_eligible:
            return {"text":"","status":"identity_unknown"}
        if actor.turn_id in self._queries:
            return self._queries[actor.turn_id]
        # Set budget before awaiting; parallel tool calls cannot both issue Search.
        self._queries[actor.turn_id]={"text":"","status":"search_in_progress"}
        while len(self._queries)>128:
            self._queries.popitem(last=False)
        try:
            from config.manage_api_client import ManageApiClient
            result=await asyncio.wait_for(ManageApiClient(conn.config).request(
                "POST","person-memory/internal/search",
                json={"actor":actor.payload(),"query":str(query)[:2048]},timeout=1),
                timeout=float(self.config.get("search_timeout_seconds",1)))
            value={"text":str((result or {}).get("text") or "")[:1500],"status":"ok"}
        except Exception:
            value={"text":"","status":"temporarily_unavailable"}
        self._queries[actor.turn_id]=value
        return value

    async def background(self,conn):
        actor=current_turn(conn)
        if actor is None:return ""
        if actor.status == "default" and actor.eligible:
            return self.short_memory or ""
        if not actor.cloud_eligible:return ""
        prior=self._portraits.get(actor.key)
        if prior and prior[0]>time.monotonic():return prior[1]
        try:
            from config.manage_api_client import ManageApiClient
            data=await ManageApiClient(conn.config).request("POST","person-memory/internal/background",json=actor.payload(),timeout=1)
            value=str((data or {}).get("text") or "")[:1500]
            self._portraits[actor.key]=(time.monotonic()+60,value)
            return value
        except Exception:return ""

    async def override(self,conn,action,match,replacement=None):
        actor=current_turn(conn)
        if actor is None or not actor.cloud_eligible:return {"status":"identity_unknown"}
        from config.manage_api_client import ManageApiClient
        await ManageApiClient(conn.config).request("POST","person-memory/internal/override",json={"actor":actor.payload(),"action":action,"match":match,"replacement":replacement},timeout=3)
        self._portraits.pop(actor.key,None)
        self._queries[actor.turn_id]={"text":"","status":"suppressed_after_change"}
        from core.utils.person_material_outbox import material_outbox
        material_outbox.suppress(actor,match)
        from core.utils.person_short_memory import invalidate
        invalidate(actor)
        # Purge old tool results, summaries, and factual context immediately.
        conn.dialogue.dialogue=[m for m in conn.dialogue.dialogue if m.role=="system"]
        conn.dialogue.invalidate_summary()
        return {"status":"accepted","cloud_sync":"pending"}
