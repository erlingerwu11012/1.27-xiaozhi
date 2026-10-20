from core.providers.tts.official.capabilities import catalog, freeze_snapshot, validate_snapshot
from core.providers.tts.official.compiler import IncrementalCompiler, SynthesisUnit, caption_from
from core.providers.tts.official.params import (
    build_continue_task,
    build_finish_task,
    build_run_task,
    canonicalize_hot_fix,
)
from core.providers.tts.official.prompt import EXPRESSIVE_STAGE_NOTICE, OFFICIAL_EXPRESSION_CONSTRAINT

def is_official_enhanced(config) -> bool:
    if not isinstance(config, dict):
        return False
    if not config.get("official_enhanced"):
        return False
    model_id = config.get("official_model_id") or config.get("model_id")
    return model_id == "TTS_QwenAudioTTSPlus"
