package xiaozhi.modules.model;

import java.util.Set;

import org.apache.commons.lang3.StringUtils;

/**
 * 回响现实官方服务的唯一默认配置来源。
 * 新建智能体 / 模板不得再写死 DeepSeek、ChatGLM、火山或阿里流式 ASR。
 */
public final class OfficialServiceDefaults {
    public static final String DISPLAY_NAME = "回响现实官方服务";

    public static final String NEW_AGENT_VAD_MODEL_ID = "VAD_SileroVAD";
    public static final String NEW_AGENT_VLLM_MODEL_ID = "VLLM_QwenVLVLLM";
    public static final String NEW_AGENT_MEMORY_MODEL_ID = "Memory_mem_local_short";
    public static final int NEW_AGENT_CHAT_HISTORY_CONF = 2;

    public static final String ASR_MODEL_ID = "ASR_Qwen3ASRRealtime";
    public static final String TTS_MODEL_ID = "TTS_QwenAudioTTSPlus";
    public static final String LLM_MODEL_ID = "LLM_QwenPlusOfficial";
    public static final String TTS_VOICE_ID = "TTS_QwenAudioTTSPlus_0001";
    public static final String TTS_VOICE_CODE = "longanlingxi";

    public static final String ASR_PROVIDER = "qwen3_asr_realtime";
    public static final String TTS_PROVIDER = "qwen_audio_tts_plus";
    public static final String LLM_PROVIDER = "openai";
    public static final String LLM_MODEL_NAME = "qwen3.7-plus";
    public static final double LLM_TEMPERATURE = 0.4;
    public static final String ASR_MODEL_NAME = "qwen3-asr-flash-realtime";
    public static final String TTS_MODEL_NAME = "qwen-audio-3.0-tts-plus";
    public static final String LLM_BASE_URL = "http://127.0.0.1:3000/v1";

    /** 旧前端 / 旧模板会提交的第三方默认值，普通创建路径必须改写为官方三项。 */
    private static final Set<String> LEGACY_ASR = Set.of(
            "ASR_AliyunStreamASR", "ASR_FunASR", "ASR_Qwen3Flash", "AliyunStreamASR", "FunASR");
    private static final Set<String> LEGACY_TTS = Set.of(
            "TTS_HuoshanDoubleStreamTTS", "HuoshanDoubleStreamTTS", "EdgeTTS", "TTS_EdgeTTS");
    private static final Set<String> LEGACY_LLM = Set.of(
            "LLM_DeepSeekLLM", "LLM_ChatGLMLLM", "DeepSeekLLM", "ChatGLMLLM", "LLM_DoubaoLLM");

    private OfficialServiceDefaults() {
    }

    public static boolean isBlankOrLegacyAsr(String modelId) {
        return StringUtils.isBlank(modelId) || LEGACY_ASR.contains(modelId.trim());
    }

    public static boolean isBlankOrLegacyTts(String modelId) {
        return StringUtils.isBlank(modelId) || LEGACY_TTS.contains(modelId.trim());
    }

    public static boolean isBlankOrLegacyLlm(String modelId) {
        return StringUtils.isBlank(modelId) || LEGACY_LLM.contains(modelId.trim());
    }

    public static boolean isOfficialAsr(String modelId) {
        return ASR_MODEL_ID.equals(modelId);
    }

    public static boolean isOfficialTts(String modelId) {
        return TTS_MODEL_ID.equals(modelId);
    }

    public static boolean isOfficialLlm(String modelId) {
        return LLM_MODEL_ID.equals(modelId);
    }
}
