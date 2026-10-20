"""Incremental compiler: LLM chunks -> complete synthesis units.

Rules:
- Do not submit half tags, tool JSON, or unclosed SSML.
- Plain text splits on sentence punctuation; over 160 Unicode chars split at
  the nearest safe punct/whitespace; without a boundary cache up to 320.
- A complete SSML document is one task; over-length SSML is rejected, never split.
- Invalid official-looking tags are stripped to caption text before upstream submit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from core.providers.tts.official.tags import ACTION_TAGS, ALL_OFFICIAL_TAGS, CONTROL_TAGS
from core.utils import textUtils

SENTENCE_END = frozenset("。！？!?；;")
SAFE_SPLIT = SENTENCE_END | frozenset("，、,;:： \t\n")
DEFAULT_SOFT_LIMIT = 160
DEFAULT_HARD_LIMIT = 320
SSML_MAX_CHARS = 20000
FORBIDDEN_SSML_PATTERNS = (
    re.compile(r"<!DOCTYPE", re.I),
    re.compile(r"<!ENTITY", re.I),
    re.compile(r"SYSTEM\s+[\"']", re.I),
    re.compile(r"<(\?xml-stylesheet|xi:include)", re.I),
)
ALLOWED_SSML_TAGS = frozenset(
    {"speak", "break", "sub", "phoneme", "say-as", "w", "s", "p", "prosody"}
)
OLD_EMOTION_RE = re.compile(r"\[emotion\s*:\s*\w+\s*\]", re.I)
TOOLISH_RE = re.compile(
    r"(<(tool_call|/tool_call|function|arguments)>)|^\s*[\{\[]\s*\"(name|arguments|tool)\"",
    re.I,
)


@dataclass
class SynthesisUnit:
    synthesis_text: str
    caption_text: str
    enable_ssml: bool = False
    rejected: bool = False
    reject_reason: str = ""
    action_count: int = 0
    stripped_invalid: List[str] = field(default_factory=list)


def _strip_official_tags(text: str) -> str:
    """只剥离白名单官方标签，保留 [选项A] 等正文方括号。"""
    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "[":
            end = text.find("]", i + 1)
            if end < 0:
                out.append(text[i:])
                break
            body = text[i + 1 : end]
            if normalize_tag_body(body) in ALL_OFFICIAL_TAGS:
                pass  # 官方标签：剥离
            else:
                out.append(text[i : end + 1])
            i = end + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def caption_from(text: str) -> str:
    if not text:
        return ""
    cleaned = OLD_EMOTION_RE.sub("", text)
    cleaned = _strip_official_tags(cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _is_complete_ssml(text: str) -> bool:
    stripped = text.strip()
    if not stripped.lower().startswith("<speak"):
        return False
    return "</speak>" in stripped.lower()


def _ssml_open(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.lower().startswith("<speak")


def _ssml_forbidden(text: str) -> Optional[str]:
    for pat in FORBIDDEN_SSML_PATTERNS:
        if pat.search(text):
            return "ssml_forbidden_construct"
    if re.search(r"<audio\b", text, re.I):
        return "ssml_external_audio_forbidden"
    tags = re.findall(r"</?([A-Za-z][\w:-]*)", text)
    for name in tags:
        if name.lower() not in ALLOWED_SSML_TAGS:
            return f"ssml_tag_not_allowed:{name}"
    return None


def normalize_tag_body(body: str) -> str:
    return " ".join(body.strip().split()).lower()


def rewrite_tags(text: str, *, max_actions: Optional[int] = None) -> tuple[str, List[str], int]:
    """Keep official tags, drop unknown bracket tags. Return synthesis, stripped, actions."""
    stripped_invalid: List[str] = []
    actions = 0

    def repl(match: re.Match) -> str:
        nonlocal actions
        raw = match.group(1)
        key = normalize_tag_body(raw)
        if key in ALL_OFFICIAL_TAGS:
            if key in ACTION_TAGS:
                if max_actions is not None and actions >= max_actions:
                    stripped_invalid.append(match.group(0))
                    return ""
                actions += 1
            return f"[{key}]" if key == normalize_tag_body(raw) else f"[{raw.strip()}]"
        stripped_invalid.append(match.group(0))
        return ""

    # Preserve original casing for multi-word official tags by mapping from whitelist.
    out = []
    i = 0
    while i < len(text):
        if text[i] == "[":
            end = text.find("]", i + 1)
            if end < 0:
                out.append(text[i:])
                break
            raw_tag = text[i : end + 1]
            body = text[i + 1 : end]
            key = normalize_tag_body(body)
            if key in ALL_OFFICIAL_TAGS:
                if key in ACTION_TAGS:
                    if max_actions is not None and actions >= max_actions:
                        stripped_invalid.append(raw_tag)
                    else:
                        actions += 1
                        # emit canonical bracket form from whitelist spelling
                        canon = next(t for t in ALL_OFFICIAL_TAGS if t == key)
                        out.append(f"[{canon}]")
                else:
                    canon = next(t for t in ALL_OFFICIAL_TAGS if t == key)
                    out.append(f"[{canon}]")
            else:
                stripped_invalid.append(raw_tag)
            i = end + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out), stripped_invalid, actions


def _incomplete_tag(text: str) -> bool:
    last_open = text.rfind("[")
    last_close = text.rfind("]")
    return last_open > last_close


def _incomplete_xml(text: str) -> bool:
    last_lt = text.rfind("<")
    last_gt = text.rfind(">")
    return last_lt > last_gt


def _last_safe_index(text: str, limit: int) -> int:
    window = text[:limit]
    for i in range(len(window) - 1, -1, -1):
        ch = window[i]
        if ch in SENTENCE_END:
            return i + 1
    for i in range(len(window) - 1, -1, -1):
        if window[i] in SAFE_SPLIT:
            return i + 1
    return -1


class IncrementalCompiler:
    def __init__(
        self,
        *,
        soft_limit: int = DEFAULT_SOFT_LIMIT,
        hard_limit: int = DEFAULT_HARD_LIMIT,
        max_actions_per_unit: int = 1,
        max_actions_per_turn: int = 2,
        dubbing: bool = False,
    ):
        self.soft_limit = soft_limit
        self.hard_limit = hard_limit
        self.max_actions_per_unit = None if dubbing else max_actions_per_unit
        self.max_actions_per_turn = None if dubbing else max_actions_per_turn
        self.dubbing = dubbing
        self._buf = ""
        self._turn_actions = 0
        self._ready: List[SynthesisUnit] = []

    def reset(self):
        self._buf = ""
        self._turn_actions = 0
        self._ready.clear()

    def feed(self, chunk: str) -> List[SynthesisUnit]:
        if not chunk:
            return []
        if TOOLISH_RE.search(chunk) and not self.dubbing:
            # Do not let tool/JSON fragments enter TTS.
            return []
        self._buf += chunk
        self._buf = OLD_EMOTION_RE.sub("", self._buf)
        self._drain(flush=False)
        out = list(self._ready)
        self._ready.clear()
        return out

    def flush(self) -> List[SynthesisUnit]:
        self._drain(flush=True)
        out = list(self._ready)
        self._ready.clear()
        self._buf = ""
        return out

    def _emit_plain(self, raw: str) -> None:
        if not raw or not raw.strip():
            remaining_actions = None
            if self.max_actions_per_turn is not None:
                remaining_actions = max(0, self.max_actions_per_turn - self._turn_actions)
            if self.max_actions_per_unit is not None:
                cap = self.max_actions_per_unit
                if remaining_actions is not None:
                    cap = min(cap, remaining_actions)
            else:
                cap = remaining_actions
            synthesis, stripped, actions = rewrite_tags(raw, max_actions=cap)
            self._turn_actions += actions
            synthesis = textUtils.strip_all_emotion_tags(synthesis)
            caption = caption_from(synthesis)
            if not synthesis.strip() and not caption:
                return
            self._ready.append(
                SynthesisUnit(
                    synthesis_text=synthesis.strip(),
                    caption_text=caption,
                    enable_ssml=False,
                    action_count=actions,
                    stripped_invalid=stripped,
                )
            )
            return
        remaining_actions = None
        if self.max_actions_per_turn is not None:
            remaining_actions = max(0, self.max_actions_per_turn - self._turn_actions)
        cap = self.max_actions_per_unit
        if cap is not None and remaining_actions is not None:
            cap = min(cap, remaining_actions)
        elif remaining_actions is not None:
            cap = remaining_actions
        synthesis, stripped, actions = rewrite_tags(raw, max_actions=cap)
        self._turn_actions += actions
        synthesis = textUtils.strip_all_emotion_tags(synthesis)
        caption = caption_from(synthesis)
        if not synthesis.strip():
            return
        self._ready.append(
            SynthesisUnit(
                synthesis_text=synthesis.strip(),
                caption_text=caption,
                enable_ssml=False,
                action_count=actions,
                stripped_invalid=stripped,
            )
        )

    def _emit_ssml(self, raw: str) -> None:
        reason = _ssml_forbidden(raw)
        if reason:
            self._ready.append(
                SynthesisUnit(
                    synthesis_text="",
                    caption_text=caption_from(raw),
                    enable_ssml=True,
                    rejected=True,
                    reject_reason=reason,
                )
            )
            return
        if len(raw) > SSML_MAX_CHARS:
            self._ready.append(
                SynthesisUnit(
                    synthesis_text="",
                    caption_text="",
                    enable_ssml=True,
                    rejected=True,
                    reject_reason="ssml_too_long",
                )
            )
            return
        self._ready.append(
            SynthesisUnit(
                synthesis_text=raw.strip(),
                caption_text=caption_from(raw),
                enable_ssml=True,
            )
        )

    def _drain(self, flush: bool) -> None:
        if _ssml_open(self._buf):
            if _is_complete_ssml(self._buf):
                self._emit_ssml(self._buf)
                self._buf = ""
            elif flush:
                self._ready.append(
                    SynthesisUnit(
                        synthesis_text="",
                        caption_text=caption_from(self._buf),
                        enable_ssml=True,
                        rejected=True,
                        reject_reason="ssml_incomplete",
                    )
                )
                self._buf = ""
            elif len(self._buf) > SSML_MAX_CHARS:
                self._ready.append(
                    SynthesisUnit(
                        synthesis_text="",
                        caption_text="",
                        enable_ssml=True,
                        rejected=True,
                        reject_reason="ssml_too_long",
                    )
                )
                self._buf = ""
            return

        if not flush and (_incomplete_tag(self._buf) or _incomplete_xml(self._buf)):
            return

        while self._buf:
            if not flush and (_incomplete_tag(self._buf) or _incomplete_xml(self._buf)):
                return
            end_idx = -1
            for i, ch in enumerate(self._buf):
                if ch in SENTENCE_END:
                    end_idx = i + 1
                    break
            if end_idx > 0:
                piece, self._buf = self._buf[:end_idx], self._buf[end_idx:]
                self._emit_plain(piece)
                continue
            if len(self._buf) >= self.soft_limit:
                split_at = _last_safe_index(self._buf, min(len(self._buf), self.hard_limit))
                if split_at > 0:
                    piece, self._buf = self._buf[:split_at], self._buf[split_at:]
                    self._emit_plain(piece)
                    continue
                if len(self._buf) >= self.hard_limit:
                    if not flush:
                        return
                    piece, self._buf = self._buf[: self.hard_limit], self._buf[self.hard_limit :]
                    self._emit_plain(piece)
                    continue
                if not flush:
                    return
            if flush:
                if self._buf.strip():
                    self._emit_plain(self._buf)
                self._buf = ""
            return
