"""The existing local short summary, scoped by account and stable person."""
import asyncio
import json
import time
import os
import threading
from pathlib import Path
from core.utils.person_material_outbox import material_outbox

_legacy_lock = threading.RLock()


def retire_legacy_agents(agents, path=None):
    """Physically remove legacy mixed summaries; retain other accounts' keys."""
    import yaml
    if path is None:
        from config.config_loader import get_project_dir
        path = Path(get_project_dir()) / "data" / ".memory.yaml"
    path = Path(path)
    with _legacy_lock:
        if not path.exists():
            return
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("invalid_legacy_summary_store")
        for agent in agents:
            data.pop(agent, None)
        temporary = path.with_name(path.name + ".retiring")
        with temporary.open("w", encoding="utf-8") as output:
            yaml.safe_dump(data, output, allow_unicode=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)


def scope(actor):
    return json.dumps([actor.account_id,actor.person_id,actor.generation,actor.agent_id], separators=(",",":"))


def schema(db):
    db.execute("CREATE TABLE IF NOT EXISTS short_summary(scope TEXT PRIMARY KEY,summary TEXT,updated INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS retired_short_scope(scope TEXT PRIMARY KEY)")
    # Legacy summaries cannot be safely attributed to a specific agent.
    db.execute("DELETE FROM short_summary WHERE json_array_length(scope)=3")
    db.execute("CREATE TABLE IF NOT EXISTS short_scope_revision(scope TEXT PRIMARY KEY,revision INTEGER NOT NULL DEFAULT 0)")
    db.execute("CREATE TABLE IF NOT EXISTS short_summary_watermark(scope TEXT PRIMARY KEY,source_ms INTEGER NOT NULL)")


def revision_scope(actor):
    return json.dumps([actor.account_id,actor.person_id,actor.generation],separators=(",",":"))


def revision(actor):
    if not actor.eligible:return 0
    with material_outbox.lock, material_outbox.connect() as db:
        schema(db)
        row=db.execute("SELECT revision FROM short_scope_revision WHERE scope=?",(revision_scope(actor),)).fetchone()
        return row[0] if row else 0


def invalidate(actor):
    if not actor.eligible:return
    with material_outbox.lock, material_outbox.connect() as db:
        schema(db)
        db.execute("DELETE FROM short_summary WHERE json_extract(scope,'$[0]')=? AND json_extract(scope,'$[1]')=? AND json_extract(scope,'$[2]')=?",(actor.account_id,actor.person_id,actor.generation))
        db.execute("INSERT INTO short_scope_revision VALUES(?,1) ON CONFLICT(scope) DO UPDATE SET revision=revision+1",(revision_scope(actor),))


def load(actor):
    if not actor.eligible:
        return ""
    with material_outbox.lock, material_outbox.connect() as db:
        schema(db)
        row = db.execute("SELECT summary FROM short_summary WHERE scope=? AND updated>?",(scope(actor),int(time.time())-86400)).fetchone()
        db.execute("DELETE FROM short_summary WHERE updated<?",(int(time.time())-86400,))
        return row[0] if row else ""


def retire(account, person, generation):
    key = json.dumps([str(account),person,generation], separators=(",",":"))
    with material_outbox.lock, material_outbox.connect() as db:
        schema(db)
        db.execute("INSERT OR IGNORE INTO retired_short_scope VALUES(?)",(key,))
        for (agent_scope,) in db.execute("SELECT scope FROM short_summary WHERE json_extract(scope,'$[0]')=? AND json_extract(scope,'$[1]')=? AND json_extract(scope,'$[2]')=?",(str(account),person,generation)).fetchall():
            db.execute("INSERT OR IGNORE INTO retired_short_scope VALUES(?)",(agent_scope,))
        for table in ("short_summary","short_scope_revision","short_summary_watermark"):
            db.execute(f"DELETE FROM {table} WHERE json_extract(scope,'$[0]')=? AND json_extract(scope,'$[1]')=? AND json_extract(scope,'$[2]')=?",(str(account),person,generation))


async def save(conn, actor, messages, summary, source_revision=None):
    if not actor.eligible:
        return
    current_revision = revision(actor)
    if source_revision is None:source_revision=current_revision
    if source_revision != current_revision:return
    llm = getattr(getattr(conn,"memory",None),"llm",None)
    if llm is None:
        return
    from core.providers.memory.mem_local_short.mem_local_short import short_term_memory_prompt_only_content
    text = "\n".join(f"{message.role}: {getattr(message,'caption_text',None) or message.content}" for message in messages if message.role in {"user","assistant"})
    if not text:
        return
    from config.manage_api_client import ManageApiClient
    state = await ManageApiClient(conn.config).request("GET",f"user-identities/internal/state/{actor.account_id}",timeout=2)
    if actor.status == "default":
        valid = state.get("mode") == "default" and state.get("default_user_id") == actor.person_id and state.get("default_generation") == actor.generation
    else:
        valid = any(member.get("user_id") == actor.person_id for member in state.get("members",[]))
    if not valid:
        return
    result = await asyncio.to_thread(llm.response_no_stream,short_term_memory_prompt_only_content,
        text+"\n历史记忆："+summary,session_id=getattr(conn,"session_id",""),max_tokens=2000,temperature=0.2)
    if not isinstance(result,str) or result.startswith("【"):
        return
    with material_outbox.lock, material_outbox.connect() as db:
        schema(db)
        row=db.execute("SELECT revision FROM short_scope_revision WHERE scope=?",(revision_scope(actor),)).fetchone()
        if (row[0] if row else 0)==source_revision and not db.execute("SELECT 1 FROM retired_short_scope WHERE scope=?",(json.dumps([actor.account_id,actor.person_id,actor.generation],separators=(",",":")),)).fetchone():
            db.execute("INSERT OR REPLACE INTO short_summary VALUES(?,?,?)",(scope(actor),result[:1800],int(time.time())))

def persist_compact(actor,dialogue):
    """Persist only the already validated compression result; no new paid call."""
    if not actor.eligible or not dialogue.compact_summary:return
    source=getattr(dialogue,"source_revision",0)
    with material_outbox.lock,material_outbox.connect() as db:
        schema(db)
        row=db.execute("SELECT revision FROM short_scope_revision WHERE scope=?",(revision_scope(actor),)).fetchone()
        retired=json.dumps([actor.account_id,actor.person_id,actor.generation],separators=(",",":"))
        watermark=int(getattr(actor,"captured_at",0) or 0)
        previous=db.execute("SELECT source_ms FROM short_summary_watermark WHERE scope=?",(scope(actor),)).fetchone()
        if (not previous or watermark>=previous[0]) and (row[0] if row else 0)==source and not db.execute("SELECT 1 FROM retired_short_scope WHERE scope=?",(retired,)).fetchone():
            db.execute("INSERT OR REPLACE INTO short_summary VALUES(?,?,?)",(scope(actor),dialogue.compact_summary,int(time.time())))
            db.execute("INSERT OR REPLACE INTO short_summary_watermark VALUES(?,?)",(scope(actor),watermark))
