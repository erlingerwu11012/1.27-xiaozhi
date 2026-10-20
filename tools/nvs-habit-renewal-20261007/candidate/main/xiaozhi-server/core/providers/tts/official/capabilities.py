"""Capability matrix for qwen-audio-3.0-tts-plus only.

Other model features listed in mixed Aliyun docs are marked official_na.
Combinations that the model does not support must be rejected before submit.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from core.providers.tts.official.tags import ACTION_TAGS, CONTROL_TAGS

MODEL = "qwen-audio-3.0-tts-plus"
OFFICIAL_MODEL_ID = "TTS_QwenAudioTTSPlus"

VERIFIED_SYSTEM_VOICES = (
    {
        "code": "longanlingxi",
        "name": "龙安灵汐",
        "languages": ["zh", "en"],
        "dialects": [],
        "ssml": True,
        "instruction": True,
        "tags": True,
        "verified": True,
    },
    {
        "code": "longanqian",
        "name": "龙安千",
        "languages": ["zh", "en"],
        "dialects": [],
        "ssml": True,
        "instruction": True,
        "tags": True,
        "verified": True,
    },
)

LANGUAGE_HINTS = (
    "zh", "en", "fr", "de", "ja", "ko", "ru", "pt", "th", "id", "vi",
    "es", "it", "ms", "fil", "ar",
)

OUTPUT_FORMATS_DEVICE = ("pcm",)
OUTPUT_FORMATS_EXPORT = ("pcm", "wav", "mp3", "opus")
SAMPLE_RATES = (8000, 16000, 22050, 24000, 44100, 48000)
DEVICE_SAMPLE_RATE = 16000

ALLOWED_RUN_PARAMS = frozenset(
    {
        "text_type",
        "voice",
        "format",
        "sample_rate",
        "volume",
        "rate",
        "pitch",
        "bit_rate",
        "enable_ssml",
        "instruction",
        "language_hints",
        "hot_fix",
        "enable_aigc_tag",
        "aigc_propagator",
        "aigc_propagate_id",
    }
)
FORBIDDEN_RUN_PARAMS = frozenset({"seed", "word_timestamp_enabled"})

UNSUPPORTED_COMBINATIONS = (
    {
        "id": "ssml_plus_incremental_continue",
        "when": "enable_ssml=true",
        "constraint": "only one continue-task is allowed",
    },
    {
        "id": "tags_require_unidirectional_submit",
        "when": "emotion/action tags",
        "constraint": "submit complete text once per unit; do not stream token fragments",
    },
    {
        "id": "aigc_tag_not_pcm",
        "when": "enable_aigc_tag with format=pcm",
        "constraint": "official watermark is wav/mp3/opus only; PCM has no AIGC tag",
    },
    {
        "id": "aigc_tag_not_pcm_device",
        "when": "enable_aigc_tag on device Opus re-encode",
        "constraint": "device path submits PCM then locally encodes Opus; that is not native Opus export and AIGC is not guaranteed",
    },
    {
        "id": "bit_rate_official_opus_kbps",
        "when": "bit_rate",
        "constraint": "Aliyun HTTP CosyVoice: opus only, 6-510 kbps. Native WS uses the same kbps field after gateway validation. Device PCM path does not send bit_rate; local 60ms Opus encode is separate from native Opus export.",
    },
    {
        "id": "designed_voice_no_dialect",
        "when": "voice from voice-design",
        "constraint": "dialect via instruction is official_na for designed voices",
    },
    {
        "id": "clone_language_not_translate",
        "when": "language_hints",
        "constraint": "language_hints is synthesis language hint, not translation",
    },
)

STATUS_PASS = "pass"
STATUS_NA = "official_na"
STATUS_UNTESTED = "untested"
STATUS_UNSUPPORTED = "unsupported_combo"


def catalog() -> Dict[str, Any]:
    return {
        "model": MODEL,
        "official_model_id": OFFICIAL_MODEL_ID,
        "display_name": "回响现实官方服务",
        "streaming": "duplex",
        "submit_mode": "sentence_unit_once",
        "excluded": ["word_timestamp_enabled", "seed"],
        "control_tags": sorted(CONTROL_TAGS),
        "action_tags": sorted(ACTION_TAGS),
        "language_hints": list(LANGUAGE_HINTS),
        "verified_system_voices": list(VERIFIED_SYSTEM_VOICES),
        "formats_device": list(OUTPUT_FORMATS_DEVICE),
        "formats_export": list(OUTPUT_FORMATS_EXPORT),
        "sample_rates": list(SAMPLE_RATES),
        "device_contract": {"sample_rate": DEVICE_SAMPLE_RATE, "channels": 1, "opus_frame_ms": 60},
        "volume": {"min": 0, "max": 100, "default": 50},
        "rate": {"min": 0.5, "max": 2.0, "default": 1.0},
        "pitch": {"min": 0.5, "max": 2.0, "default": 1.0},
        "instruction_max_chars": 100,
        "bit_rate": {"unit": "kbps", "min": 6, "max": 510, "formats": ["opus"]},
        "hot_fix": {
            "official": {"replace": [{"啊": "你好世界"}], "pronunciation": [{"天气": "tian1 qi4"}]},
            "platform_simplified": "object-of-strings converted server-side to replace[]",
        },
        "unsupported_combinations": list(UNSUPPORTED_COMBINATIONS),
        "voice_clone": {
            "model": "voice-enrollment",
            "target_model": MODEL,
            "recommended_seconds": [10, 20],
            "max_prompt_audio_length": [3.0, 30.0],
        },
        "voice_design": {"supported": True, "dialect": STATUS_NA},
    }


def _coalesce(snapshot: Dict[str, Any], key: str, default: Any, caster):
    if key not in snapshot or snapshot[key] is None:
        return caster(default)
    return caster(snapshot[key])


def validate_snapshot(snapshot: Dict[str, Any], *, export: bool = False) -> Tuple[bool, str]:
    voice = snapshot.get("voice")
    verified = {v["code"] for v in VERIFIED_SYSTEM_VOICES}
    allowed = snapshot.get("allowed_voices")
    if isinstance(allowed, (list, tuple, set)):
        authorized = voice in verified or voice in set(allowed)
    else:
        authorized = voice in verified
    if not authorized:
        return False, f"voice_not_authorized:{voice}"
    fmt = snapshot.get("format") or "pcm"
    allowed_fmt = OUTPUT_FORMATS_EXPORT if export else OUTPUT_FORMATS_DEVICE
    if export:
        if fmt not in OUTPUT_FORMATS_EXPORT:
            return False, f"format_not_supported:{fmt}"
    else:
        # device playback always pcm upstream then opus locally; other formats converted server-side
        if fmt not in OUTPUT_FORMATS_EXPORT:
            return False, f"format_not_supported:{fmt}"
    sr = _coalesce(snapshot, "sample_rate", DEVICE_SAMPLE_RATE, int)
    if sr not in SAMPLE_RATES:
        return False, f"sample_rate_not_supported:{sr}"
    volume = _coalesce(snapshot, "volume", 50, int)
    if volume < 0 or volume > 100:
        return False, "volume_out_of_range"
    rate = _coalesce(snapshot, "rate", 1.0, float)
    if rate < 0.5 or rate > 2.0:
        return False, "rate_out_of_range"
    pitch = _coalesce(snapshot, "pitch", 1.0, float)
    if pitch < 0.5 or pitch > 2.0:
        return False, "pitch_out_of_range"
    hints = snapshot.get("language_hints")
    if hints:
        if not isinstance(hints, (list, tuple)) or not hints:
            return False, "language_hints_invalid"
        if hints[0] not in LANGUAGE_HINTS:
            return False, f"language_hint_not_supported:{hints[0]}"
        voice_meta = next((v for v in VERIFIED_SYSTEM_VOICES if v["code"] == voice), None)
        if voice_meta and hints[0] not in voice_meta["languages"] and hints[0] != "zh":
            # unverified language for this voice: do not pretend support
            if hints[0] not in voice_meta["languages"]:
                return False, f"voice_language_unverified:{voice}:{hints[0]}"
    dialect = snapshot.get("dialect")
    if dialect:
        voice_meta = next((v for v in VERIFIED_SYSTEM_VOICES if v["code"] == voice), None)
        if snapshot.get("voice_kind") == "design":
            return False, "designed_voice_no_dialect"
        if voice_meta and dialect not in voice_meta.get("dialects", []) and not snapshot.get("instruction"):
            # dialect via instruction is allowed for clone/system if instruction set
            return False, f"dialect_unverified_for_voice:{voice}:{dialect}"
    instruction = snapshot.get("instruction") or ""
    if len(instruction) > 100:
        return False, "instruction_too_long"
    if snapshot.get("enable_ssml") and snapshot.get("incremental"):
        return False, "ssml_plus_incremental_continue"
    fmt_l = str(fmt).lower()
    if snapshot.get("enable_aigc_tag") and fmt_l == "pcm":
        return False, "aigc_not_supported_for_format"
    if snapshot.get("bit_rate") is not None:
        if fmt_l != "opus":
            return False, "bit_rate_format"
        try:
            br = int(snapshot["bit_rate"])
        except (TypeError, ValueError):
            return False, "invalid_bit_rate"
        if br < 6 or br > 510:
            return False, "invalid_bit_rate"
    extra = snapshot.get("extra_params") or {}
    for key in list(snapshot.keys()) + list(extra.keys()):
        if key in FORBIDDEN_RUN_PARAMS:
            return False, f"forbidden_param:{key}"
    unknown = [
        k for k in extra if k not in ALLOWED_RUN_PARAMS and k not in FORBIDDEN_RUN_PARAMS
    ]
    if unknown:
        return False, f"unknown_param:{unknown[0]}"
    return True, "ok"


def freeze_snapshot(config: Dict[str, Any]) -> Dict[str, Any]:
    hints = config.get("language_hints") or config.get("languageHints")
    if isinstance(hints, str) and hints:
        hints = [hints]
    voice = (
        config.get("private_voice")
        or config.get("voice")
        or config.get("ttsVoiceId")
        or "longanlingxi"
    )
    verified = {v["code"] for v in VERIFIED_SYSTEM_VOICES}
    allowed = config.get("allowed_voices")
    if not isinstance(allowed, (list, tuple, set)):
        allowed = []
    owner_ok = voice in verified or voice in set(allowed)
    return {
        "model": config.get("model") or MODEL,
        "voice": voice,
        "format": config.get("format") or "pcm",
        "sample_rate": _coalesce(config, "sample_rate", DEVICE_SAMPLE_RATE, int),
        "volume": _coalesce(config, "volume", 50, int),
        "rate": _coalesce(config, "rate", 1.0, float),
        "pitch": _coalesce(config, "pitch", 1.0, float),
        "bit_rate": config.get("bit_rate"),
        "instruction": (config.get("instruction") or "")[:100],
        "language_hints": list(hints) if hints else None,
        "hot_fix": config.get("hot_fix") or config.get("hotFix"),
        "enable_aigc_tag": bool(config.get("enable_aigc_tag")),
        "aigc_propagator": config.get("aigc_propagator"),
        "aigc_propagate_id": config.get("aigc_propagate_id"),
        "voice_status": config.get("voice_status") or ("available" if voice in verified else None),
        "voice_owner_ok": owner_ok,
        "allowed_voices": list(allowed) if allowed else list(verified),
        "voice_kind": config.get("voice_kind") or ("system" if voice in verified else "private"),
        "dialect": config.get("dialect"),
        "price_version": config.get("price_version"),
        "official_enhanced": True,
    }
