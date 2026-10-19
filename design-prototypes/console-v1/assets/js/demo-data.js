/* 演示数据（DEMO ONLY）
 * 本文件只服务于静态视觉原型，不来自任何真实接口或账号。
 * 字段名对齐现有接口返回：/agent/list（agentName、llmModelName、ttsModelName、ttsVoiceName、
 * deviceCount、lastConnectedAt、memModelId、systemPrompt）与设备列表（model、firmwareVersion、
 * macAddress、bindTime、lastConversation、remark）。正式接入时由 Api.agent / Api.device 提供。
 * 注意：deviceCount 是“已绑定设备数”，不是“在线设备数”；接口没有在线状态字段。 */
(function () {
  const now = Date.now();
  const ago = (min) => (min == null ? null : new Date(now - min * 60000));

  window.DEMO = {
    user: { username: 'demo_user（演示）' },
    balance: { points: 1280, source: 'cache' },   // 来源：oneapi | cache | none

    memoryModes: [
      { value: 'Memory_mem_local_short', label: '本地短期记忆' },
      { value: 'Memory_bailian', label: '长期记忆 · 回响现实官方服务' },
      { value: 'Memory_nomem', label: '无记忆' },
    ],

    // 人设预设：取自 src/constants/personaPresets.js
    personaPresets: [
      { id: 'natural', name: '自然朋友', description: '随和坦诚，接话也分享看法' },
      { id: 'listener', name: '温柔倾听', description: '温和体贴，回应具体感受' },
      { id: 'humorous', name: '轻松幽默', description: '机敏有趣，笑点落在情境上' },
      { id: 'rational', name: '理性交流', description: '沉稳直接，用日常话说清理由' },
      { id: 'partner', name: '做事搭档', description: '务实可靠，求助时一起理清重点' },
      { id: 'playful', name: '俏皮调侃', description: '机灵带点小坏，玩笑有分寸' },
    ],

    // 模型下拉选项：演示占位，正式版来自模型列表接口
    modelOptions: {
      VAD: ['SileroVAD（示例）'],
      ASR: ['FunASR 本地识别（示例）', '阿里云语音识别（示例）'],
      LLM: ['通义千问 Qwen-Plus（示例）', '通义千问 Qwen-Turbo（示例）'],
      VLLM: ['通义千问 VL（示例）', '不启用'],
      Intent: ['LLM 意图识别（示例）', '函数调用（示例）'],
      TTS: ['CosyVoice（示例）', 'Edge TTS（示例）'],
      Voice: ['龙小淳（示例）', '龙婉（示例）', '晓晓（示例）'],
    },

    agents: [
      {
        id: 'demo-a1', agentName: '小念', avatar: 'assets/img/avatar-xiaonian.png',
        llmModelName: '通义千问 Qwen-Plus（示例）', ttsModelName: 'CosyVoice（示例）', ttsVoiceName: '龙小淳（示例）',
        memModelId: 'Memory_bailian', lastConnectedAt: ago(12), preset: 'natural', userNickname: '你',
        languageCode: 'zh_CN', language: '中文', chatReport: 2,
        systemPrompt: '你是小念，一个住在书桌上的陪伴伙伴。说话自然坦诚，会接住对方的话，也分享自己的看法。',
        devices: [
          { id: 'demo-d1', model: '小念桌面版（示例）', firmwareVersion: '1.6.2', macAddress: 'A4:CF:12:3B:7E:01',
            bindTime: '2026-10-12 21:04', lastConversation: ago(12), remark: '书桌' },
          { id: 'demo-d2', model: '小念桌面版（示例）', firmwareVersion: '1.6.0', macAddress: 'A4:CF:12:3B:91:5C',
            bindTime: '2026-10-15 09:30', lastConversation: ago(60 * 26), remark: '卧室' },
        ],
      },
      {
        id: 'demo-a2', agentName: '晚安电台', avatar: null,
        llmModelName: '通义千问 Qwen-Turbo（示例）', ttsModelName: 'CosyVoice（示例）', ttsVoiceName: '龙婉（示例）',
        memModelId: 'Memory_mem_local_short', lastConnectedAt: ago(60 * 5 + 20), preset: 'listener', userNickname: '朋友',
        languageCode: 'zh_CN', language: '中文', chatReport: 1,
        systemPrompt: '睡前陪聊的角色，语气温和，回应具体的感受，不急着给建议。',
        devices: [
          { id: 'demo-d3', model: '小念桌面版（示例）', firmwareVersion: '1.6.2', macAddress: 'B8:D6:1A:04:22:E9',
            bindTime: '2026-10-08 22:41', lastConversation: ago(60 * 5 + 20), remark: '' },
        ],
      },
      {
        id: 'demo-a3', agentName: '学习搭子', avatar: null,
        llmModelName: '通义千问 Qwen-Plus（示例）', ttsModelName: 'Edge TTS（示例）', ttsVoiceName: '晓晓（示例）',
        memModelId: 'Memory_nomem', lastConnectedAt: null, preset: 'partner', userNickname: '同学',
        languageCode: 'zh_CN', language: '中文', chatReport: 1,
        systemPrompt: '务实可靠的学习伙伴，帮忙理清重点和步骤。',
        devices: [],
      },
      {
        id: 'demo-a4', agentName: '英语练习', avatar: null,
        llmModelName: '通义千问 Qwen-Turbo（示例）', ttsModelName: 'Edge TTS（示例）', ttsVoiceName: '晓晓（示例）',
        memModelId: 'Memory_mem_local_short', lastConnectedAt: ago(60 * 24 * 3), preset: 'rational', userNickname: 'friend',
        languageCode: 'en_US', language: 'English', chatReport: 1,
        systemPrompt: 'A patient English speaking partner. Keep sentences short and correct gently.',
        devices: [],
      },
    ],
  };
})();
