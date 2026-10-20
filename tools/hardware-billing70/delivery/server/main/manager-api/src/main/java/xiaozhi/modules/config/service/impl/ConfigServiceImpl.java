package xiaozhi.modules.config.service.impl;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;

import lombok.AllArgsConstructor;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.exception.ErrorCode;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.redis.RedisKeys;
import xiaozhi.common.redis.RedisUtils;
import xiaozhi.common.utils.ConvertUtils;
import xiaozhi.common.utils.JsonUtils;
import xiaozhi.modules.agent.dao.AgentVoicePrintDao;
import xiaozhi.modules.agent.entity.AgentEntity;
import xiaozhi.modules.agent.entity.AgentPluginMapping;
import xiaozhi.modules.agent.entity.AgentTemplateEntity;
import xiaozhi.modules.agent.entity.AgentVoicePrintEntity;
import xiaozhi.modules.agent.service.AgentMcpAccessPointService;
import xiaozhi.modules.agent.service.AgentPluginMappingService;
import xiaozhi.modules.agent.service.AgentService;
import xiaozhi.modules.agent.service.AgentTemplateService;
import xiaozhi.modules.agent.vo.AgentVoicePrintVO;
import xiaozhi.modules.config.service.ConfigService;
import xiaozhi.modules.device.entity.DeviceEntity;
import xiaozhi.modules.device.service.DeviceService;
import xiaozhi.modules.model.entity.ModelConfigEntity;
import xiaozhi.modules.model.service.ModelConfigService;
import xiaozhi.modules.sys.dto.SysParamsDTO;
import xiaozhi.modules.sys.service.SysParamsService;
import xiaozhi.modules.pay.service.OneApiBindingService;
import xiaozhi.modules.pay.vo.OneApiDeviceTokenVO;
import xiaozhi.modules.officialtts.service.OfficialTtsService;
import xiaozhi.modules.timbre.service.TimbreService;
import xiaozhi.modules.timbre.vo.TimbreDetailsVO;
import xiaozhi.modules.useridentity.service.UserIdentityService;
import xiaozhi.modules.useridentity.service.AccountIdentityStateService;

@Service
@AllArgsConstructor
public class ConfigServiceImpl implements ConfigService {
    private final SysParamsService sysParamsService;
    private final DeviceService deviceService;
    private final ModelConfigService modelConfigService;
    private final AgentService agentService;
    private final AgentTemplateService agentTemplateService;
    private final RedisUtils redisUtils;
    private final TimbreService timbreService;
    private final AgentPluginMappingService agentPluginMappingService;
    private final AgentMcpAccessPointService agentMcpAccessPointService;
    private final AgentVoicePrintDao agentVoicePrintDao;
    private final UserIdentityService userIdentityService;
    private final AccountIdentityStateService identityState;
    private final OneApiBindingService oneApiBindingService;
    private final OfficialTtsService officialTtsService;
    private final xiaozhi.modules.pay.service.HardwareBillingPolicy hardwareBillingPolicy;

    @Override
    public Object getConfig(Boolean isCache) {
        if (isCache) {
            // 先从Redis获取配置
            Object cachedConfig = redisUtils.get(RedisKeys.getServerConfigKey());
            if (cachedConfig != null) {
                return cachedConfig;
            }
        }

        // 构建配置信息
        Map<String, Object> result = new HashMap<>();
        buildConfig(result);

        // 查询默认智能体
        AgentTemplateEntity agent = agentTemplateService.getDefaultTemplate();
        if (agent == null) {
            throw new RenException(ErrorCode.AGENT_TEMPLATE_NOT_FOUND);
        }

        // 构建模块配置
        buildModuleConfig(
                null,
                null,
                null,
                null,
                null,
                null,
                agent.getVadModelId(),
                agent.getAsrModelId(),
                null,
                null,
                null,
                null,
                null,
                null,
                result,
                isCache);

        // 将配置存入Redis
        redisUtils.set(RedisKeys.getServerConfigKey(), result);

        return result;
    }

    @Override
    public Map<String, Object> getAgentModels(String macAddress, Map<String, String> selectedModule) {
        // 根据MAC地址查找设备
        DeviceEntity device = deviceService.getDeviceByMacAddress(macAddress);
        if (device == null) {
            // 如果设备，去redis里看看有没有需要连接的设备
            String cachedCode = deviceService.geCodeByDeviceId(macAddress);
            if (StringUtils.isNotBlank(cachedCode)) {
                throw new RenException(ErrorCode.OTA_DEVICE_NEED_BIND, cachedCode);
            }
            throw new RenException(ErrorCode.OTA_DEVICE_NOT_FOUND);
        }

        // 获取智能体信息
        AgentEntity agent = agentService.getAgentById(device.getAgentId());
        if (agent == null) {
            throw new RenException(ErrorCode.AGENT_NOT_FOUND);
        }
        // 获取音色信息
        String voice = null;
        String referenceAudio = null;
        String referenceText = null;
        TimbreDetailsVO timbre = timbreService.get(agent.getTtsVoiceId());
        if (timbre != null) {
            voice = timbre.getTtsVoice();
            referenceAudio = timbre.getReferenceAudio();
            referenceText = timbre.getReferenceText();
        } else {
            // 克隆音色功能已移除，voice 保持 null
        }
        // 构建返回数据
        Map<String, Object> result = new HashMap<>();

        // 下发自定义名称和用户昵称
        result.put("agent_id",agent.getId());
        String devName = StringUtils.isBlank(device.getDeviceName()) ? "小智" : device.getDeviceName();
        String nickName = StringUtils.isBlank(device.getUserNickname()) ? "主人" : device.getUserNickname();
        result.put("device_name", devName);
        result.put("user_nickname", nickName);

        // 获取单台设备每天最多输出字数
        String deviceMaxOutputSize = sysParamsService.getValue("device_max_output_size", true);
        result.put("device_max_output_size", deviceMaxOutputSize);

        // 获取聊天记录配置
        Integer chatHistoryConf = agent.getChatHistoryConf();
        if (agent.getMemModelId() != null && agent.getMemModelId().equals(Constant.MEMORY_NO_MEM)) {
            chatHistoryConf = Constant.ChatHistoryConfEnum.IGNORE.getCode();
        } else if (agent.getMemModelId() != null
                && !agent.getMemModelId().equals(Constant.MEMORY_NO_MEM)
                && agent.getChatHistoryConf() == null) {
            chatHistoryConf = Constant.ChatHistoryConfEnum.RECORD_TEXT_AUDIO.getCode();
        }
        result.put("chat_history_conf", chatHistoryConf);

        // Official TTS: mode + kill-switch; never treat empty allowlist as open.
        boolean officialTts = xiaozhi.modules.model.OfficialServiceDefaults.isOfficialTts(agent.getTtsModelId());
        boolean enhancedForUser = device.getUserId() != null
                && officialTtsService.enhancedEnabledFor(device.getUserId());
        result.put("official_tts_enhanced", officialTts && enhancedForUser);
        result.put("official_tts_enhanced_mode", officialTtsService.enhancedMode());
        if (device.getUserId() != null) {
            result.put("sys_user_id", device.getUserId());
            result.put("identity_state",identityState.snapshot(device.getUserId()));
        }
        Map<String, Object> boundOfficialVoice = new HashMap<>();
        if (StringUtils.isNotBlank(agent.getOfficialTtsJson())) {
            Map<String, Object> saved = JsonUtils.parseObject(
                    agent.getOfficialTtsJson(),
                    new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {});
            Object boundVoiceValue = saved == null ? null : saved.get("voice");
            if (saved != null && "available".equals(saved.get("voice_status")) && boundVoiceValue instanceof String
                    && StringUtils.isNotBlank((String) boundVoiceValue)) {
                boundOfficialVoice.put("voice", voice);
            }
        }
        result.put("official_tts", boundOfficialVoice);

        String alreadySelectedVadModelId = (String) selectedModule.get("VAD");
        if (alreadySelectedVadModelId != null && alreadySelectedVadModelId.equals(agent.getVadModelId())) {
            agent.setVadModelId(null);
        }
        String alreadySelectedAsrModelId = (String) selectedModule.get("ASR");
        if (alreadySelectedAsrModelId != null && alreadySelectedAsrModelId.equals(agent.getAsrModelId())) {
            agent.setAsrModelId(null);
        }

        // 添加函数调用参数信息
        if (!Objects.equals(agent.getIntentModelId(), "Intent_nointent")) {
            String agentId = agent.getId();
            List<AgentPluginMapping> pluginMappings = agentPluginMappingService.agentPluginParamsByAgentId(agentId);
            if (pluginMappings != null && !pluginMappings.isEmpty()) {
                Map<String, Object> pluginParams = new HashMap<>();
                for (AgentPluginMapping pluginMapping : pluginMappings) {
                    pluginParams.put(pluginMapping.getProviderCode(), pluginMapping.getParamInfo());
                }
                result.put("plugins", pluginParams);
            }
        }
        // 获取mcp接入点地址
        String mcpEndpoint = agentMcpAccessPointService.getAgentMcpAccessAddress(agent.getId());
        if (StringUtils.isNotBlank(mcpEndpoint) && mcpEndpoint.startsWith("ws")) {
            mcpEndpoint = mcpEndpoint.replace("/mcp/", "/call/");
            result.put("mcp_endpoint", mcpEndpoint);
        }
        // 获取声纹信息
        buildVoiceprintConfig(agent.getId(), result);
        // face-api 的 usr_* 仅通过显式绑定映射为统一 user_id，供新固件消费。
        if (device.getUserId() != null) {
            result.put("face_identity_bindings", userIdentityService.getFaceBindings(device.getUserId()));
        }

        // 构建模块配置
        buildModuleConfig(
                agent.getAgentName(),
                agent.getSystemPrompt(),
                agent.getSummaryMemory(),
                voice,
                referenceAudio,
                referenceText,
                agent.getVadModelId(),
                agent.getAsrModelId(),
                agent.getLlmModelId(),
                agent.getVllmModelId(),
                agent.getTtsModelId(),
                agent.getMemModelId(),
                agent.getIntentModelId(),
                null,
                result,
                true);

        return result;
    }

    /**
     * 构建配置信息
     * 
     * @param config 系统参数列表
     * @return 配置信息
     */
    private Object buildConfig(Map<String, Object> config) {

        // 查询所有系统参数
        List<SysParamsDTO> paramsList = sysParamsService.list(new HashMap<>());

        for (SysParamsDTO param : paramsList) {
            String[] keys = param.getParamCode().split("\\.");
            Map<String, Object> current = config;

            // 遍历除最后一个key之外的所有key
            for (int i = 0; i < keys.length - 1; i++) {
                String key = keys[i];
                if (!current.containsKey(key)) {
                    current.put(key, new HashMap<String, Object>());
                }
                current = (Map<String, Object>) current.get(key);
            }

            // 处理最后一个key
            String lastKey = keys[keys.length - 1];
            String value = param.getParamValue();

            // 根据valueType转换值
            switch (param.getValueType().toLowerCase()) {
                case "number":
                    try {
                        double doubleValue = Double.parseDouble(value);
                        // 如果数值是整数形式，则转换为Integer
                        if (doubleValue == (int) doubleValue) {
                            current.put(lastKey, (int) doubleValue);
                        } else {
                            current.put(lastKey, doubleValue);
                        }
                    } catch (NumberFormatException e) {
                        current.put(lastKey, value);
                    }
                    break;
                case "boolean":
                    current.put(lastKey, Boolean.parseBoolean(value));
                    break;
                case "array":
                    // 将分号分隔的字符串转换为数字数组
                    List<String> list = new ArrayList<>();
                    for (String num : value.split(";")) {
                        if (StringUtils.isNotBlank(num)) {
                            list.add(num.trim());
                        }
                    }
                    current.put(lastKey, list);
                    break;
                case "json":
                    try {
                        current.put(lastKey, JsonUtils.parseObject(value, Object.class));
                    } catch (Exception e) {
                        current.put(lastKey, value);
                    }
                    break;
                default:
                    current.put(lastKey, value);
            }
        }

        return config;
    }

    /**
     * 构建声纹配置信息
     * 
     * @param agentId 智能体ID
     * @param result  结果Map
     */
    private void buildVoiceprintConfig(String agentId, Map<String, Object> result) {
        try {
            // 获取声纹接口地址
            String voiceprintUrl = sysParamsService.getValue("server.voice_print", true);
            if (StringUtils.isBlank(voiceprintUrl) || "null".equals(voiceprintUrl)) {
                return;
            }

            // 获取智能体关联的声纹信息（不需要用户权限验证）
            List<AgentVoicePrintVO> voiceprints = getVoiceprintsByAgentId(agentId);
            if (voiceprints == null || voiceprints.isEmpty()) {
                return;
            }

            // 构建speakers列表
            List<String> speakers = new ArrayList<>();
            List<Map<String, Object>> speakerProfiles = new ArrayList<>();
            for (AgentVoicePrintVO voiceprint : voiceprints) {
                String displayName = voiceprint.getSourceName();
                Map<String, Object> user = null;
                if (StringUtils.isNotBlank(voiceprint.getUserId()) && voiceprint.getCreator() != null) {
                    user = userIdentityService.getActiveUser(voiceprint.getCreator(), voiceprint.getUserId());
                    if (user != null) {
                        displayName = String.valueOf(user.get("display_name"));
                    }
                }
                if (user == null || !"ready".equals(voiceprint.getBindingState())) continue;
                String speakerStr = String.format("%s,%s,%s",
                        voiceprint.getVectorId(),
                        displayName,
                        voiceprint.getIntroduce() != null ? voiceprint.getIntroduce() : "");
                speakers.add(speakerStr);
                Map<String, Object> profile = new HashMap<>();
                profile.put("speaker_id", voiceprint.getVectorId());
                profile.put("voiceprint_id",voiceprint.getId());
                profile.put("template_version",voiceprint.getTemplateVersion());
                profile.put("user_id", user == null ? null : user.get("user_id"));
                profile.put("display_name", displayName);
                profile.put("introduce", voiceprint.getIntroduce() != null ? voiceprint.getIntroduce() : "");
                speakerProfiles.add(profile);
            }

            // 构建声纹配置
            Map<String, Object> voiceprintConfig = new HashMap<>();
            voiceprintConfig.put("url", voiceprintUrl);
            voiceprintConfig.put("speakers", speakers);
            voiceprintConfig.put("speaker_profiles", speakerProfiles);

            // 获取声纹识别相似度阈值，默认0.4
            String thresholdStr = sysParamsService.getValue("server.voiceprint_similarity_threshold", true);
            if (StringUtils.isNotBlank(thresholdStr) && !"null".equals(thresholdStr)) {
                try {
                    double threshold = Double.parseDouble(thresholdStr);
                    voiceprintConfig.put("similarity_threshold", threshold);
                } catch (NumberFormatException e) {
                    // 如果解析失败，使用默认值0.4
                    voiceprintConfig.put("similarity_threshold", 0.4);
                }
            } else {
                voiceprintConfig.put("similarity_threshold", 0.4);
            }

            result.put("voiceprint", voiceprintConfig);
        } catch (Exception e) {
            // 声纹配置获取失败时不影响其他功能
            System.err.println("获取声纹配置失败: " + e.getMessage());
        }
    }

    /**
     * 获取智能体关联的声纹信息
     * 
     * @param agentId 智能体ID
     * @return 声纹信息列表
     */
    private List<AgentVoicePrintVO> getVoiceprintsByAgentId(String agentId) {
        LambdaQueryWrapper<AgentVoicePrintEntity> queryWrapper = new LambdaQueryWrapper<>();
        AgentEntity agent=agentService.getAgentById(agentId);
        if (agent == null || agent.getUserId() == null) return List.of();
        queryWrapper.eq(AgentVoicePrintEntity::getCreator, agent.getUserId());
        queryWrapper.isNotNull(AgentVoicePrintEntity::getUserId);
        queryWrapper.orderByAsc(AgentVoicePrintEntity::getCreateDate);
        List<AgentVoicePrintEntity> entities = agentVoicePrintDao.selectList(queryWrapper);
        return ConvertUtils.sourceToTarget(entities, AgentVoicePrintVO.class);
    }

    /**
     * 构建模块配置
     * 
     * @param prompt         提示词
     * @param voice          音色
     * @param referenceAudio 参考音频路径
     * @param referenceText  参考文本
     * @param vadModelId     VAD模型ID
     * @param asrModelId     ASR模型ID
     * @param llmModelId     LLM模型ID
     * @param ttsModelId     TTS模型ID
     * @param memModelId     记忆模型ID
     * @param intentModelId  意图模型ID
     * @param result         结果Map
     */
    private void buildModuleConfig(
            String assistantName,
            String prompt,
            String summaryMemory,
            String voice,
            String referenceAudio,
            String referenceText,
            String vadModelId,
            String asrModelId,
            String llmModelId,
            String vllmModelId,
            String ttsModelId,
            String memModelId,
            String intentModelId,
            String ragModelId,
            Map<String, Object> result,
            boolean isCache) {
        Map<String, String> selectedModule = new HashMap<>();

        String[] modelTypes = { "VAD", "ASR", "TTS", "Memory", "Intent", "LLM", "VLLM", "RAG" };
        String[] modelIds = { vadModelId, asrModelId, ttsModelId, memModelId, intentModelId, llmModelId, vllmModelId,
                ragModelId };
        String intentLLMModelId = null;
        String memLocalShortLLMModelId = null;

        for (int i = 0; i < modelIds.length; i++) {
            if (modelIds[i] == null) {
                continue;
            }
            // 关键：第三个参数传false，确保获取原始密钥
            ModelConfigEntity model = modelConfigService.getModelByIdFromCache(modelIds[i]);
            if (model == null) {
                continue;
            }
            Map<String, Object> typeConfig = new HashMap<>();
            if (model.getConfigJson() != null) {
                Map<String, Object> copied = JsonUtils.parseObject(
                        JsonUtils.toJsonString(model.getConfigJson()),
                        new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {
                        });
                if (copied == null) {
                    copied = new HashMap<>();
                }
                hardwareBillingPolicy.configure(copied,result,modelTypes[i],"llm");
                typeConfig.put(model.getId(), copied);
                // 如果是TTS类型，添加private_voice属性（写副本，禁止改共享对象）
                if ("TTS".equals(modelTypes[i])) {
                    if (voice != null)
                        copied.put("private_voice", voice);
                    if (referenceAudio != null)
                        copied.put("ref_audio", referenceAudio);
                    if (referenceText != null)
                        copied.put("ref_text", referenceText);
                    copied.put("official_model_id", model.getId());
                    if (xiaozhi.modules.model.OfficialServiceDefaults.isOfficialTts(model.getId())) {
                        copied.put("official_enhanced", Boolean.TRUE.equals(result.get("official_tts_enhanced")));
                        Object officialCfg = result.get("official_tts");
                        if (officialCfg instanceof Map) {
                            Object boundVoice = ((Map<?, ?>) officialCfg).get("voice");
                            if (boundVoice instanceof String && StringUtils.isNotBlank((String) boundVoice)) {
                                copied.put("voice", boundVoice);
                            }
                        }
                        copied.remove("voice_owner_ok");
                        Object rawUser = result.get("sys_user_id");
                        if (rawUser instanceof Number) {
                            copied.put("allowed_voices",
                                    officialTtsService.allowedVoiceCodes(((Number) rawUser).longValue()));
                        } else {
                            copied.put("allowed_voices", java.util.List.of("longanlingxi", "longanqian"));
                        }
                        if (Boolean.TRUE.equals(copied.get("official_enhanced"))) {
                            injectCustomerTtsToken(copied, result);
                        }
                    } else {
                        copied.put("official_enhanced", false);
                    }

                    Map<String, Object> map = copied;
                    if (Constant.VOICE_CLONE_HUOSHAN_DOUBLE_STREAM.equals(map.get("type"))) {
                        if (voice != null && voice.startsWith("S_")) {
                            map.put("resource_id", "seed-icl-1.0");
                        }
                    }
                }
                // 如果是Intent类型，且type=intent_llm，则给他添加附加模型
                if ("Intent".equals(modelTypes[i])) {
                    Map<String, Object> map = copied;
                    if ("intent_llm".equals(map.get("type"))) {
                        intentLLMModelId = (String) map.get("llm");
                        if (StringUtils.isNotBlank(intentLLMModelId) && intentLLMModelId.equals(llmModelId)) {
                            intentLLMModelId = null;
                        }
                    }
                    if (map.get("functions") != null) {
                        String functionStr = (String) map.get("functions");
                        if (StringUtils.isNotBlank(functionStr)) {
                            String[] functions = functionStr.split("\\;");
                            map.put("functions", functions);
                        }
                    }
                }
                if ("Memory".equals(modelTypes[i])) {
                    Map<String, Object> map = copied;
                    if ("mem_local_short".equals(map.get("type"))) {
                        memLocalShortLLMModelId = (String) map.get("llm");
                        if (StringUtils.isNotBlank(memLocalShortLLMModelId)
                                && memLocalShortLLMModelId.equals(llmModelId)) {
                            memLocalShortLLMModelId = null;
                        }
                    }
                }
                // 如果是LLM类型，且intentLLMModelId不为空，则添加附加模型
                if ("LLM".equals(modelTypes[i])) {
                    if (StringUtils.isNotBlank(intentLLMModelId)) {
                        if (!typeConfig.containsKey(intentLLMModelId)) {
                            // 修改这里：添加isMaskSensitive=false参数
                            ModelConfigEntity intentLLM = modelConfigService.getModelByIdFromCache(intentLLMModelId);
                            Map<String,Object> extraCopy=JsonUtils.parseObject(JsonUtils.toJsonString(intentLLM.getConfigJson()),
                                    new com.fasterxml.jackson.core.type.TypeReference<Map<String,Object>>() {});
                            if(extraCopy==null) extraCopy=new HashMap<>();
                            hardwareBillingPolicy.configure(extraCopy,result,"LLM","llm");
                            typeConfig.put(intentLLM.getId(),extraCopy);
                        }
                    }
                    if (StringUtils.isNotBlank(memLocalShortLLMModelId)) {
                        if (!typeConfig.containsKey(memLocalShortLLMModelId)) {
                            // 修改这里：添加isMaskSensitive=false参数
                            ModelConfigEntity memLocalShortLLM = modelConfigService
                                    .getModelByIdFromCache(memLocalShortLLMModelId);
                            Map<String,Object> extraCopy=JsonUtils.parseObject(JsonUtils.toJsonString(memLocalShortLLM.getConfigJson()),
                                    new com.fasterxml.jackson.core.type.TypeReference<Map<String,Object>>() {});
                            if(extraCopy==null) extraCopy=new HashMap<>();
                            hardwareBillingPolicy.configure(extraCopy,result,"LLM","summary");
                            typeConfig.put(memLocalShortLLM.getId(),extraCopy);
                        }
                    }
                }
            }
            result.put(modelTypes[i], typeConfig);

            selectedModule.put(modelTypes[i], model.getId());
        }

        result.put("selected_module", selectedModule);
        if (StringUtils.isNotBlank(prompt)) {
            prompt = prompt.replace("{{assistant_name}}", StringUtils.isBlank(assistantName) ? "小智" : assistantName);
        }
        result.put("prompt", prompt);
        result.put("summaryMemory", summaryMemory);
    }

    /**
     * Replace the shared production TTS token with the customer's one-api device token.
     * Never logs the secret. Failure is recorded as official_billing=token_resolve_failed.
     */
    private void injectCustomerTtsToken(Map<String, Object> copied, Map<String, Object> result) {
        copied.remove("api_key");
        Object rawUser = result.get("sys_user_id");
        if (!(rawUser instanceof Number)) {
            copied.put("official_billing", "token_resolve_failed");
            copied.put("official_tts_blocked", "token_resolve_failed");
            copied.put("official_enhanced", false);
            return;
        }
        try {
            OneApiDeviceTokenVO vo = oneApiBindingService.resolveDeviceToken(((Number) rawUser).longValue());
            if (vo != null && StringUtils.isNotBlank(vo.getToken())) {
                copied.put("api_key", vo.getToken());
                copied.put("official_billing", "customer_device_token");
            } else {
                copied.put("official_billing", "token_resolve_failed");
                copied.put("official_tts_blocked", "token_resolve_failed");
                copied.put("official_enhanced", false);
            }
        } catch (Exception e) {
            copied.put("official_billing", "token_resolve_failed");
            copied.put("official_tts_blocked", "token_resolve_failed");
            copied.put("official_enhanced", false);
        }
    }
}
