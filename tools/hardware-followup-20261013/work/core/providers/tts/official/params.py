"""Build native duplex run-task / continue-task / finish-task payloads."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from core.providers.tts.official.capabilities import ALLOWED_RUN_PARAMS, FORBIDDEN_RUN_PARAMS, MODEL


def _coalesce(snapshot, key, default, caster):
    if key not in snapshot or snapshot[key] is None:
        return caster(default)
    return caster(snapshot[key])


def canonicalize_hot_fix(raw: Any) -> Any:
    """Convert platform-internal dict-of-strings into official replace/pronunciation."""
    if raw is None or raw == "" or raw == {}:
        return None
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError("hot_fix_must_be_object")
    if "replace" in raw or "pronunciation" in raw:
        for key in raw:
            if key not in ("replace", "pronunciation"):
                raise ValueError("hot_fix_unknown_field")
        out: Dict[str, Any] = {}
        for field in ("replace", "pronunciation"):
            if field not in raw:
                continue
            arr = raw[field]
            if not isinstance(arr, list):
                raise ValueError("hot_fix_rules_must_be_array")
            cleaned = []
            for item in arr:
                if not isinstance(item, dict) or len(item) != 1:
                    raise ValueError("hot_fix_rule_must_be_single_key_object")
                k, v = next(iter(item.items()))
                if not isinstance(k, str) or not isinstance(v, str):
                    raise ValueError("hot_fix_value_must_be_string")
                cleaned.append({k: v})
            out[field] = cleaned
        return out
    replace = []
    for k, v in raw.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError("hot_fix_value_must_be_string")
        replace.append({k: v})
    return {"replace": replace}


def build_run_task(task_id: str, snapshot: Dict[str, Any], *, enable_ssml: bool = False) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "text_type": "PlainText",
        "voice": snapshot.get("voice") or "longanlingxi",
        "format": snapshot.get("format") or "pcm",
        "sample_rate": _coalesce(snapshot, "sample_rate", 16000, int),
        "volume": _coalesce(snapshot, "volume", 50, int),
        "rate": _coalesce(snapshot, "rate", 1.0, float),
        "pitch": _coalesce(snapshot, "pitch", 1.0, float),
    }
    if snapshot.get("bit_rate") is not None:
        if params["format"] != "opus":
            raise ValueError("bit_rate_format")
        br = int(snapshot["bit_rate"])
        if br < 6 or br > 510:
            raise ValueError("invalid_bit_rate")
        params["bit_rate"] = br
    if enable_ssml:
        params["enable_ssml"] = True
    instruction = (snapshot.get("instruction") or "").strip()
    dialect = (snapshot.get("dialect") or "").strip()
    if dialect and "方言" not in instruction and dialect not in instruction:
        instruction = f"请用{dialect}表达。{instruction}".strip()
    if instruction:
        params["instruction"] = instruction[:100]
    hints = snapshot.get("language_hints")
    if hints:
        params["language_hints"] = [hints[0]] if isinstance(hints, (list, tuple)) else [str(hints)]
    if snapshot.get("hot_fix"):
        params["hot_fix"] = canonicalize_hot_fix(snapshot["hot_fix"])
    if snapshot.get("enable_aigc_tag") and params["format"] != "pcm":
        params["enable_aigc_tag"] = True
        if snapshot.get("aigc_propagator"):
            params["aigc_propagator"] = snapshot["aigc_propagator"]
        if snapshot.get("aigc_propagate_id"):
            params["aigc_propagate_id"] = snapshot["aigc_propagate_id"]
    for key in list(params):
        if key in FORBIDDEN_RUN_PARAMS or key not in ALLOWED_RUN_PARAMS:
            raise ValueError(f"illegal_run_param:{key}")
    return {
        "header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"},
        "payload": {
            "task_group": "audio",
            "task": "tts",
            "function": "SpeechSynthesizer",
            "model": snapshot.get("model") or MODEL,
            "parameters": params,
            "input": {},
        },
    }


def build_continue_task(task_id: str, text: str) -> Dict[str, Any]:
    return {
        "header": {"action": "continue-task", "task_id": task_id, "streaming": "duplex"},
        "payload": {"input": {"text": text}},
    }


def build_finish_task(task_id: str, *, cancel: bool = False) -> Dict[str, Any]:
    payload_input: Dict[str, Any] = {"directive": "cancel"} if cancel else {}
    return {
        "header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"},
        "payload": {"input": payload_input},
    }
