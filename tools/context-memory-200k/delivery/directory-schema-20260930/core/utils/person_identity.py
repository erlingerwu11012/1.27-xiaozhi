"""Trusted, immutable voice actor. No identity is inferred from conversation text."""
from __future__ import annotations
from contextvars import ContextVar
from dataclasses import dataclass, asdict
from collections import OrderedDict
import copy
import uuid
import time

_turn = ContextVar("person_turn", default=None)


@dataclass(frozen=True)
class PersonTurn:
    account_id: str
    person_id: str
    generation: int
    directory_version: int
    mode: str
    status: str
    turn_id: str
    device_id: str
    agent_id: str
    listen_epoch: int
    voiceprint_id: str = ""
    template_version: int = 0
    display_name: str = ""
    captured_at: int = 0

    @property
    def eligible(self):
        return bool(self.account_id and self.person_id and self.status in {"matched", "default"})

    @property
    def key(self):
        if not self.eligible:
            return (self.account_id, "unknown", self.turn_id)
        return (self.account_id, self.person_id, self.generation)

    def payload(self):
        return asdict(self)


def reset_speaker(conn):
    conn.current_speaker_user = None
    conn.current_speaker = None
    conn.person_turn = None


def freeze(conn, state, match=None, *, status="unknown", epoch=None):
    config = getattr(conn, "config", {}) or {}
    account = str(config.get("sys_user_id") or "")
    mode = state.get("mode", "unavailable") if isinstance(state, dict) else "unavailable"
    capabilities = getattr(getattr(conn,"mcp_client",None),"capabilities",{}).get("experimental",{})
    if mode == "personal" and (capabilities.get("personalIdentity",0) < 2 or capabilities.get("identityCleanup",0) < 2):
        mode = "unavailable"
    if capabilities.get("personalIdentity",0) >= 2 and getattr(conn,"identity_synced_version",None) != (state or {}).get("directory_version"):
        mode = "unavailable"
    person, name, voice, version, generation = "", "", "", 0, 0
    if account and mode == "default" and state.get("default_user_id"):
        person = str(state["default_user_id"])
        generation = int(state.get("default_generation") or 0)
        status, name = "default", "默认用户"
    elif account and mode == "personal" and isinstance(match, dict):
        # Validate against the server directory captured for this audio.
        candidates = state.get("voice_profiles") or []
        candidate = next((p for p in candidates if p.get("speaker_id") == match.get("speaker_id")
                          and p.get("user_id") == match.get("user_id")), None)
        if candidate:
            person = str(candidate["user_id"])
            name = str(candidate.get("display_name") or "")
            voice = str(candidate.get("voiceprint_id") or "")
            version = int(candidate.get("template_version") or 0)
            status = "matched"
    selected = (config.get("selected_module") or {})
    actor = PersonTurn(account, person, generation, int((state or {}).get("directory_version") or 0),
                       mode, status, uuid.uuid4().hex, str(getattr(conn, "device_id", "") or ""),
                       str(config.get("agent_id") or config.get("agentId") or getattr(conn,"agent_id","") or ""),
                       int(getattr(conn, "listen_epoch", 0) if epoch is None else epoch),
                       voice, version, name, int(time.time()*1000))
    conn.person_turn = actor
    conn.current_speaker_user = {"user_id":person,"display_name":name,"speaker_id":voice} if actor.eligible else None
    conn.current_speaker = name or None
    return actor


def current_turn(conn):
    value = _turn.get()
    if value and value[0] is conn:
        return value[1]
    return None


def activate(conn, actor):
    return _turn.set((conn,actor))


def deactivate(token):
    _turn.reset(token)


async def refresh_directory(conn):
    """Fresh authority per audio; outage cannot turn personal mode into default."""
    epoch = getattr(conn, "listen_epoch", 0)
    session = getattr(conn, "session_id", None)
    def still_current():
        return (epoch == getattr(conn, "listen_epoch", 0)
                and session == getattr(conn, "session_id", None))
    try:
        from config.manage_api_client import ManageApiClient
        account = str((conn.config or {}).get("sys_user_id") or "")
        if not account:
            raise ValueError("account_missing")
        state = await ManageApiClient(conn.config).request(
            "GET", f"user-identities/internal/state/{account}", timeout=2)
        if not isinstance(state, dict) or str(state.get("account_id")) != account:
            raise ValueError("directory_account_mismatch")
        from core.utils.person_directory_sync import normalize_directory
        state = normalize_directory(state)
        if not still_current():
            return state
        conn.identity_state = copy.deepcopy(state)
        from core.utils.person_directory_sync import schedule_directory_sync
        schedule_directory_sync(conn, conn.identity_state)
        provider = getattr(conn, "voiceprint_provider", None)
        if provider is None and state.get("voice_profiles"):
            import asyncio
            voice_config = dict(conn.config.get("voiceprint") or {})
            if not voice_config.get("url"):
                # The first voiceprint may be bound while this WebSocket stays open.
                # Its connection-time agent configuration had no voiceprint URL.
                fresh = await ManageApiClient(conn.config).request(
                    "POST", "config/agent-models",
                    json={"macAddress": conn.device_id,
                          "clientId": (getattr(conn, "headers", None) or {}).get("client-id") or conn.device_id,
                          "selectedModule": conn.config.get("selected_module") or {}},
                    timeout=3)
                if (not isinstance(fresh, dict)
                        or str(fresh.get("sys_user_id") or "") != account
                        or str(fresh.get("agent_id") or "") != str(getattr(conn, "agent_id", "") or "")):
                    raise ValueError("voiceprint_config_scope_mismatch")
                updated = fresh.get("voiceprint") or {}
                if not isinstance(updated, dict) or not updated.get("url"):
                    raise ValueError("voiceprint_url_missing")
                voice_config["url"] = updated["url"]
                if "similarity_threshold" in updated:
                    voice_config["similarity_threshold"] = updated["similarity_threshold"]
            voice_config["speakers"] = state["voice_profiles"]
            voice_config["speaker_profiles"] = state["voice_profiles"]
            conn.config["voiceprint"] = voice_config
            await asyncio.to_thread(conn._initialize_voiceprint)
            provider=getattr(conn,"voiceprint_provider",None)
        if not still_current():
            return state
        if provider is not None:
            provider.speakers = state.get("voice_profiles") or []
            provider.speaker_map = provider._parse_speakers()
            provider.speaker_ids = list(provider.speaker_map)
            provider.enabled = bool(provider.api_url and provider.api_key and provider.speaker_ids)
        return conn.identity_state
    except Exception:
        unavailable = {"mode":"unavailable","directory_version":0}
        if still_current():
            conn.identity_state = unavailable
        return unavailable


def select_dialogue(conn, actor):
    from core.utils.dialogue import Dialogue
    histories = getattr(conn,"_person_dialogues",None)
    if histories is None:
        histories = conn._person_dialogues = OrderedDict()
    # Unknown speakers share only this continuous anonymous session. The nullable
    # actor remains ineligible; this key is never a persistent person identifier.
    import time
    marker = (actor.account_id, actor.mode, actor.directory_version)
    previous = getattr(conn, "_anonymous_marker", None)
    expired = time.monotonic() - getattr(conn, "_anonymous_seen", 0) > int((conn.config or {}).get("close_connection_no_voice_time", 120))
    if actor.eligible or marker != previous or expired:
        for old in list(histories):
            if len(old) > 1 and old[1] == "unknown":
                histories[old].invalidate_summary()
                histories.pop(old, None)
                getattr(conn, "_person_dialogue_actors", {}).pop(old, None)
        conn._anonymous_segment = uuid.uuid4().hex
    conn._anonymous_marker = marker
    conn._anonymous_seen = time.monotonic()
    key = actor.key if actor.eligible else (actor.account_id, "unknown", getattr(conn, "session_id", ""), conn._anonymous_segment)
    if key not in histories:
        dialogue=Dialogue()
        dialogue.configure_compact(conn.config)
        dialogue.update_system_message(getattr(conn,"prompt","") or "")
        histories[key]=dialogue
    histories.move_to_end(key)
    while len(histories)>16:
        _, removed = histories.popitem(last=False)
        removed.invalidate_summary()
    conn.dialogue=histories[key]
    if actor.eligible:
        from core.utils.person_short_memory import revision
        latest = revision(actor)
        if getattr(conn.dialogue, "source_revision", latest) != latest:
            conn.dialogue.invalidate_summary()
            conn.dialogue.dialogue[:] = [m for m in conn.dialogue.dialogue if m.role == "system"]
        conn.dialogue.source_revision = latest
    if not hasattr(conn,"_person_dialogue_actors"):conn._person_dialogue_actors={}
    conn._person_dialogue_actors[key]=actor
    # Old agent/device summary is mixed data and cannot be assigned to an actor.
    if getattr(conn,"memory",None) is not None and not getattr(conn.memory,"personal",False):
        from core.utils.person_short_memory import load
        conn.memory.short_memory=load(actor)
        conn.memory.role_id=":".join(map(str,key))
        conn.memory.person_context=True
