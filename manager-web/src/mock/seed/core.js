/**
 * 共享的核心演示数据：账号、智能体、设备、模型选项、音色、插件、字典。
 * 其他模块的种子（知识库、账单、TTS……）在各自的 seed 文件里，引用这里的 id。
 *
 * 标注规则：用户自己的数据（账号、智能体、设备备注……）一律带“演示”字样；
 * MAC 地址使用本地管理地址段 02:xx，不会与真实设备重合。
 */
import { seed, minutesAgo, nowStr } from '../core';

export const DEMO_USERS = {
  user: { id: 'demo-u-1001', username: 'demo_user', label: '演示普通用户' },
  admin: { id: 'demo-u-9001', username: 'demo_admin', label: '演示管理员' },
};

const daysAgo = (d, h = 10) => nowStr(new Date(Date.now() - d * 86400000 - h * 3600000));

seed(() => ({
  users: [
    { id: DEMO_USERS.user.id, username: DEMO_USERS.user.username, superAdmin: 0, status: 1, mobile: '', createDate: daysAgo(40), deviceCount: 3 },
    { id: DEMO_USERS.admin.id, username: DEMO_USERS.admin.username, superAdmin: 1, status: 1, mobile: '', createDate: daysAgo(120), deviceCount: 1 },
    { id: 'demo-u-1002', username: 'demo_xiaoming', superAdmin: 0, status: 1, mobile: '+8613800000001', createDate: daysAgo(18), deviceCount: 0 },
    { id: 'demo-u-1003', username: 'demo_xiaohong', superAdmin: 0, status: 0, mobile: '+8613800000002', createDate: daysAgo(9), deviceCount: 2 },
    { id: 'demo-u-1004', username: 'demo_tester', superAdmin: 0, status: 1, mobile: '', createDate: daysAgo(3), deviceCount: 0 },
  ],
  sessions: {},

  agents: [
    {
      id: 'demo-a-1', userId: DEMO_USERS.user.id, agentCode: 'AGT_DEMO_1', agentName: '小念（演示）', deviceName: '小念', userNickname: '同桌',
      asrModelId: 'ASR_Qwen3ASRRealtime', vadModelId: 'VAD_SileroVAD', llmModelId: 'LLM_QwenPlusOfficial', vllmModelId: 'VLLM_QwenVLVLLM',
      ttsModelId: 'TTS_QwenAudioTTSPlus', ttsVoiceId: 'TTS_QwenAudioTTSPlus_0001', memModelId: 'Memory_bailian', intentModelId: 'Intent_function_call',
      chatHistoryConf: 2, summaryMemory: '', langCode: 'zh_CN', language: '中文', sort: 1,
      systemPrompt: '你是小念，一个住在书桌上的陪伴伙伴。说话自然坦诚，会接住对方的话，也分享自己的看法。对方忙的时候少打扰，累了就陪着聊几句。',
      functions: [{ pluginId: 'SYSTEM_PLUGIN_WEATHER', paramInfo: { default_location: '杭州' } }],
      createdAt: daysAgo(30), lastConnectedAt: minutesAgo(12),
    },
    {
      id: 'demo-a-2', userId: DEMO_USERS.user.id, agentCode: 'AGT_DEMO_2', agentName: '晚安电台（演示）', deviceName: '晚安电台', userNickname: '朋友',
      asrModelId: 'ASR_Qwen3ASRRealtime', vadModelId: 'VAD_SileroVAD', llmModelId: 'LLM_QwenTurbo', vllmModelId: 'VLLM_QwenVLVLLM',
      ttsModelId: 'TTS_QwenAudioTTSPlus', ttsVoiceId: 'TTS_QwenAudioTTSPlus_0002', memModelId: 'Memory_mem_local_short', intentModelId: 'Intent_function_call',
      chatHistoryConf: 1, summaryMemory: '', langCode: 'zh_CN', language: '中文', sort: 2,
      systemPrompt: '睡前陪聊的角色。语气温和，声音放轻，回应对方具体的感受，不急着给建议；对方说困了，就道一声晚安。',
      functions: [], createdAt: daysAgo(21), lastConnectedAt: minutesAgo(60 * 5 + 20),
    },
    {
      id: 'demo-a-3', userId: DEMO_USERS.user.id, agentCode: 'AGT_DEMO_3', agentName: '学习搭子（演示）', deviceName: '学习搭子', userNickname: '同学',
      asrModelId: 'ASR_Qwen3ASRRealtime', vadModelId: 'VAD_SileroVAD', llmModelId: 'LLM_QwenPlusOfficial', vllmModelId: 'VLLM_QwenVLVLLM',
      ttsModelId: 'TTS_EdgeTTS', ttsVoiceId: 'TTS_EdgeTTS_0001', memModelId: 'Memory_nomem', intentModelId: 'Intent_function_call',
      chatHistoryConf: 2, summaryMemory: '', langCode: 'zh_CN', language: '中文', sort: 3,
      systemPrompt: '务实可靠的学习伙伴。帮对方理清重点和步骤，一次只推进一小步；卡住的时候先问清楚卡在哪里。',
      functions: [], createdAt: daysAgo(6), lastConnectedAt: null,
    },
    {
      id: 'demo-a-4', userId: DEMO_USERS.user.id, agentCode: 'AGT_DEMO_4', agentName: '英语练习（演示）', deviceName: 'English Buddy', userNickname: 'friend',
      asrModelId: 'ASR_Qwen3ASRRealtime', vadModelId: 'VAD_SileroVAD', llmModelId: 'LLM_QwenTurbo', vllmModelId: 'VLLM_QwenVLVLLM',
      ttsModelId: 'TTS_EdgeTTS', ttsVoiceId: 'TTS_EdgeTTS_0002', memModelId: 'Memory_mem_local_short', intentModelId: 'Intent_function_call',
      chatHistoryConf: 1, summaryMemory: '', langCode: 'en_US', language: 'English', sort: 4,
      systemPrompt: 'A patient English speaking partner. Keep sentences short and correct gently.',
      functions: [], createdAt: daysAgo(3), lastConnectedAt: daysAgo(3, 2),
    },
    {
      id: 'demo-a-9', userId: DEMO_USERS.admin.id, agentCode: 'AGT_DEMO_9', agentName: '测试机器人（演示）', deviceName: '测试', userNickname: '管理员',
      asrModelId: 'ASR_Qwen3ASRRealtime', vadModelId: 'VAD_SileroVAD', llmModelId: 'LLM_QwenPlusOfficial', vllmModelId: 'VLLM_QwenVLVLLM',
      ttsModelId: 'TTS_QwenAudioTTSPlus', ttsVoiceId: 'TTS_QwenAudioTTSPlus_0001', memModelId: 'Memory_mem_local_short', intentModelId: 'Intent_function_call',
      chatHistoryConf: 2, summaryMemory: '', langCode: 'zh_CN', language: '中文', sort: 1,
      systemPrompt: '用于后台联调检查的测试角色，回答简短。',
      functions: [], createdAt: daysAgo(60), lastConnectedAt: daysAgo(1, 4),
    },
  ],

  // board / appVersion / macAddress / alias / createDate / lastConnectedAt —— 与 /device/bind 返回字段一致
  devices: [
    { id: 'demo-d-1', agentId: 'demo-a-1', userId: DEMO_USERS.user.id, board: 'xiaonian-desk', appVersion: '1.6.2', macAddress: '02:00:5E:10:00:01', alias: '书桌（演示）', createDate: daysAgo(12, 2), lastConnectedAt: minutesAgo(12), autoUpdate: 1 },
    { id: 'demo-d-2', agentId: 'demo-a-1', userId: DEMO_USERS.user.id, board: 'xiaonian-desk', appVersion: '1.6.0', macAddress: '02:00:5E:10:00:02', alias: '卧室（演示）', createDate: daysAgo(4, 1), lastConnectedAt: minutesAgo(60 * 26), autoUpdate: 1 },
    { id: 'demo-d-3', agentId: 'demo-a-2', userId: DEMO_USERS.user.id, board: 'xiaonian-desk', appVersion: '1.6.2', macAddress: '02:00:5E:10:00:03', alias: '', createDate: daysAgo(11, 4), lastConnectedAt: minutesAgo(60 * 5 + 20), autoUpdate: 0 },
    { id: 'demo-d-9', agentId: 'demo-a-9', userId: DEMO_USERS.admin.id, board: 'xiaonian-desk', appVersion: '1.6.2', macAddress: '02:00:5E:10:00:09', alias: '联调样机（演示）', createDate: daysAgo(50), lastConnectedAt: daysAgo(1, 4), autoUpdate: 1 },
  ],
  /** 设备开机播报的 6 位绑定码（演示）：绑定后消耗。任何未列出的 6 位码会返回“验证码无效” */
  bindCodes: ['123456', '246810', '135790', '888888'],

  // 模型配置（/models/*）。modelType 与原页面使用的类型一致
  models: [
    { id: 'VAD_SileroVAD', modelType: 'VAD', modelCode: 'SileroVAD', modelName: 'SileroVAD 语音活动检测', isDefault: 1, isEnabled: 1, sort: 1 },
    { id: 'ASR_Qwen3ASRRealtime', modelType: 'ASR', modelCode: 'Qwen3ASRRealtime', modelName: '通义千问实时语音识别', isDefault: 1, isEnabled: 1, sort: 1 },
    { id: 'ASR_FunASR', modelType: 'ASR', modelCode: 'FunASR', modelName: 'FunASR 本地识别', isDefault: 0, isEnabled: 1, sort: 2 },
    { id: 'LLM_QwenPlusOfficial', modelType: 'LLM', modelCode: 'QwenPlusOfficial', modelName: '通义千问 Qwen-Plus', type: 'openai', isDefault: 1, isEnabled: 1, sort: 1 },
    { id: 'LLM_QwenTurbo', modelType: 'LLM', modelCode: 'QwenTurbo', modelName: '通义千问 Qwen-Turbo', type: 'openai', isDefault: 0, isEnabled: 1, sort: 2 },
    { id: 'VLLM_QwenVLVLLM', modelType: 'VLLM', modelCode: 'QwenVLVLLM', modelName: '通义千问 VL 视觉', isDefault: 1, isEnabled: 1, sort: 1 },
    { id: 'Intent_function_call', modelType: 'Intent', modelCode: 'function_call', modelName: '函数调用意图识别', isDefault: 1, isEnabled: 1, sort: 1 },
    { id: 'Intent_nointent', modelType: 'Intent', modelCode: 'nointent', modelName: '不使用意图识别', isDefault: 0, isEnabled: 1, sort: 2 },
    { id: 'Memory_mem_local_short', modelType: 'Memory', modelCode: 'mem_local_short', modelName: '本地短期记忆', isDefault: 1, isEnabled: 1, sort: 1 },
    { id: 'Memory_bailian', modelType: 'Memory', modelCode: 'bailian', modelName: '长期记忆 · 回响现实官方服务', isDefault: 0, isEnabled: 1, sort: 2 },
    { id: 'Memory_nomem', modelType: 'Memory', modelCode: 'nomem', modelName: '无记忆', isDefault: 0, isEnabled: 1, sort: 3 },
    { id: 'TTS_QwenAudioTTSPlus', modelType: 'TTS', modelCode: 'QwenAudioTTSPlus', modelName: '回响现实官方服务', isDefault: 1, isEnabled: 1, sort: 1 },
    { id: 'TTS_EdgeTTS', modelType: 'TTS', modelCode: 'EdgeTTS', modelName: 'Edge TTS', isDefault: 0, isEnabled: 1, sort: 2 },
  ],
  ttsVoices: [
    { id: 'TTS_QwenAudioTTSPlus_0001', ttsModelId: 'TTS_QwenAudioTTSPlus', name: '温柔女声（演示）', ttsVoice: 'Cherry', languages: '中文', sort: 1, remark: '' },
    { id: 'TTS_QwenAudioTTSPlus_0002', ttsModelId: 'TTS_QwenAudioTTSPlus', name: '沉稳男声（演示）', ttsVoice: 'Ethan', languages: '中文', sort: 2, remark: '' },
    { id: 'TTS_QwenAudioTTSPlus_0003', ttsModelId: 'TTS_QwenAudioTTSPlus', name: '活泼少女（演示）', ttsVoice: 'Chelsie', languages: '中文、英文', sort: 3, remark: '' },
    { id: 'TTS_EdgeTTS_0001', ttsModelId: 'TTS_EdgeTTS', name: '晓晓（演示）', ttsVoice: 'zh-CN-XiaoxiaoNeural', languages: '中文', sort: 1, remark: '' },
    { id: 'TTS_EdgeTTS_0002', ttsModelId: 'TTS_EdgeTTS', name: 'Jenny（演示）', ttsVoice: 'en-US-JennyNeural', languages: '英文', sort: 2, remark: '' },
  ],
  // 插件：fields 是 JSON 字符串，与 roleConfig 中 JSON.parse(item.fields) 的读取方式一致
  plugins: [
    { id: 'SYSTEM_PLUGIN_WEATHER', name: '天气查询', providerCode: 'get_weather', fields: JSON.stringify([{ key: 'default_location', label: '默认城市', type: 'string', default: '北京' }]) },
    { id: 'SYSTEM_PLUGIN_NEWS', name: '新闻播报', providerCode: 'get_news', fields: JSON.stringify([{ key: 'default_rss_url', label: 'RSS 地址', type: 'string', default: '' }]) },
    { id: 'SYSTEM_PLUGIN_MUSIC', name: '本地音乐', providerCode: 'play_music', fields: '[]' },
    { id: 'SYSTEM_PLUGIN_ROLE', name: '切换角色', providerCode: 'change_role', fields: '[]' },
  ],

  // 字典数据：dictType → [{ key, name }]，与 /admin/dict/data/type/{type} 的读取方式一致
  dictByType: {
    FIRMWARE_TYPE: [
      { key: 'xiaonian-desk', name: '小念桌面版（演示）' },
      { key: 'esp32-s3-box', name: 'ESP32-S3-BOX（演示）' },
      { key: 'bread-compact-wifi', name: '面包板 Wi-Fi 版（演示）' },
    ],
    MOBILE_AREA: [
      { key: '+86', name: '中国大陆' },
      { key: '+852', name: '中国香港' },
      { key: '+1', name: '美国 / 加拿大' },
    ],
  },
}));

// 演示账户余额（点）。只存在于本机演示数据中
seed(() => ({
  accounts: {
    [DEMO_USERS.user.id]: { balance: 1280 },
    [DEMO_USERS.admin.id]: { balance: 50000 },
  },
}));
