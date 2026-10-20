"""Official Qwen-Audio-TTS Plus control and paralinguistic tags."""

from __future__ import annotations

CONTROL_TAGS = frozenset({
    "sad", "amazed", "deep and loud shouting", "trembling", "angry", "excited",
    "sarcastic", "curious", "like dracula", "bored", "tired", "scornful",
    "shouting", "asmr", "panicked", "mischievously", "empathetic", "whispers",
    "reluctantly", "crying", "serious", "very slowly", "very fast",
})

ACTION_TAGS = frozenset({
    "gasp", "sighing", "clears throat", "giggles", "laughing", "cough", "snorts",
})

ALL_OFFICIAL_TAGS = CONTROL_TAGS | ACTION_TAGS
RESTRICTED_AUTO_ACTIONS = frozenset({"cough", "crying", "gasp", "snorts"})
