package xiaozhi.modules.model.service;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;

import lombok.AllArgsConstructor;
import xiaozhi.common.exception.ErrorCode;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.agent.entity.AgentEntity;
import xiaozhi.modules.agent.entity.AgentTemplateEntity;
import xiaozhi.modules.model.OfficialServiceDefaults;
import xiaozhi.modules.model.entity.ModelConfigEntity;
import xiaozhi.modules.timbre.entity.TimbreEntity;
import xiaozhi.modules.timbre.service.TimbreService;

/**
 * 官方 ASR/TTS/LLM 默认配置的后端唯一入口。
 * 缺失或禁用时失败，不静默退回 DeepSeek / ChatGLM / 火山。
 */
@Service
@AllArgsConstructor
public class OfficialModelService {
    private final ModelConfigService modelConfigService;
    private final TimbreService timbreService;

    public void applyToNewAgent(AgentEntity entity) {
        requireOfficialEnabled();
        requireEnabled(OfficialServiceDefaults.NEW_AGENT_VLLM_MODEL_ID, "VLLM");
        requireEnabled(OfficialServiceDefaults.NEW_AGENT_MEMORY_MODEL_ID, "Memory");
        entity.setAsrModelId(OfficialServiceDefaults.ASR_MODEL_ID);
        entity.setTtsModelId(OfficialServiceDefaults.TTS_MODEL_ID);
        entity.setLlmModelId(OfficialServiceDefaults.LLM_MODEL_ID);
        entity.setTtsVoiceId(OfficialServiceDefaults.TTS_VOICE_ID);
        entity.setVadModelId(OfficialServiceDefaults.NEW_AGENT_VAD_MODEL_ID);
        entity.setVllmModelId(OfficialServiceDefaults.NEW_AGENT_VLLM_MODEL_ID);
        entity.setMemModelId(OfficialServiceDefaults.NEW_AGENT_MEMORY_MODEL_ID);
        entity.setChatHistoryConf(OfficialServiceDefaults.NEW_AGENT_CHAT_HISTORY_CONF);
    }

    public void applyToNewTemplate(AgentTemplateEntity template) {
        requireOfficialEnabled();
        template.setAsrModelId(OfficialServiceDefaults.ASR_MODEL_ID);
        template.setTtsModelId(OfficialServiceDefaults.TTS_MODEL_ID);
        template.setLlmModelId(OfficialServiceDefaults.LLM_MODEL_ID);
        template.setTtsVoiceId(OfficialServiceDefaults.TTS_VOICE_ID);
    }

    /**
     * 普通创建：空值或旧前端默认值改写为官方三项。
     * 管理员提交的其它已启用配置予以保留。
     */
    public void applyOfficialUnlessExplicit(AgentTemplateEntity template, boolean forceOfficial) {
        requireOfficialEnabled();
        if (forceOfficial || StringUtils.isBlank(template.getAsrModelId())) {
            template.setAsrModelId(OfficialServiceDefaults.ASR_MODEL_ID);
        } else {
            requireEnabled(template.getAsrModelId(), "ASR");
        }
        if (forceOfficial || StringUtils.isBlank(template.getTtsModelId())) {
            template.setTtsModelId(OfficialServiceDefaults.TTS_MODEL_ID);
            template.setTtsVoiceId(OfficialServiceDefaults.TTS_VOICE_ID);
        } else {
            requireEnabled(template.getTtsModelId(), "TTS");
        }
        if (forceOfficial || StringUtils.isBlank(template.getLlmModelId())) {
            template.setLlmModelId(OfficialServiceDefaults.LLM_MODEL_ID);
        } else {
            requireEnabled(template.getLlmModelId(), "LLM");
        }
        if (StringUtils.isBlank(template.getTtsVoiceId())
                || OfficialServiceDefaults.TTS_MODEL_ID.equals(template.getTtsModelId())) {
            template.setTtsVoiceId(resolveOfficialVoice(template.getTtsVoiceId()));
        }
    }

    public void requireOfficialEnabled() {
        requireEnabled(OfficialServiceDefaults.ASR_MODEL_ID, "ASR");
        requireEnabled(OfficialServiceDefaults.TTS_MODEL_ID, "TTS");
        requireEnabled(OfficialServiceDefaults.LLM_MODEL_ID, "LLM");
        requireOfficialVoice();
    }

    public void requireEnabled(String modelId, String expectedType) {
        if (StringUtils.isBlank(modelId)) {
            throw new RenException(ErrorCode.OFFICIAL_SERVICE_CONFIG_MISSING);
        }
        ModelConfigEntity model = modelConfigService.getModelByIdFromCache(modelId);
        if (model == null || model.getIsEnabled() == null || model.getIsEnabled() != 1) {
            if (isOfficialId(modelId)) {
                throw new RenException(ErrorCode.OFFICIAL_SERVICE_CONFIG_MISSING);
            }
            throw new RenException(ErrorCode.MODEL_CONFIG_DISABLED);
        }
        if (StringUtils.isNotBlank(expectedType) && StringUtils.isNotBlank(model.getModelType())
                && !expectedType.equalsIgnoreCase(model.getModelType())) {
            throw new RenException(ErrorCode.MODEL_CONFIG_DISABLED);
        }
    }

    public String resolveOfficialVoice(String requestedVoiceId) {
        TimbreEntity voice = timbreService.selectById(OfficialServiceDefaults.TTS_VOICE_ID);
        if (voice == null) {
            throw new RenException(ErrorCode.OFFICIAL_SERVICE_CONFIG_MISSING);
        }
        if (StringUtils.isNotBlank(requestedVoiceId)) {
            TimbreEntity requested = timbreService.selectById(requestedVoiceId);
            if (requested != null
                    && OfficialServiceDefaults.TTS_MODEL_ID.equals(requested.getTtsModelId())) {
                return requestedVoiceId;
            }
        }
        return OfficialServiceDefaults.TTS_VOICE_ID;
    }

    private void requireOfficialVoice() {
        TimbreEntity voice = timbreService.selectById(OfficialServiceDefaults.TTS_VOICE_ID);
        if (voice == null || !OfficialServiceDefaults.TTS_MODEL_ID.equals(voice.getTtsModelId())) {
            throw new RenException(ErrorCode.OFFICIAL_SERVICE_CONFIG_MISSING);
        }
    }

    private static boolean isOfficialId(String modelId) {
        return OfficialServiceDefaults.isOfficialAsr(modelId)
                || OfficialServiceDefaults.isOfficialTts(modelId)
                || OfficialServiceDefaults.isOfficialLlm(modelId);
    }
}
