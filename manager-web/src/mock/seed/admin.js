/**
 * 系统管理的演示数据：更多演示账号、系统参数、模型供应器、模型调用配置（configJson）、
 * 补充模型 / 音色、字典类型与字典数据。
 *
 * 规则：
 * - 密钥类字段只保存明显的占位值（sk-demo-**** / demo-****），不保存任何看起来像真实密钥的内容；
 * - 地址一律使用保留域名 *.demo.example，不会指向真实服务；
 * - 本文件的数据通过 ensureAdminData(db) 合并进运行时数据库：
 *   新数据库（或“重置演示数据”后）合并一次；已经存在于浏览器里的旧演示库也会补齐缺少的部分，
 *   用 db.__xnAdmin 记录版本，避免把管理员删掉的演示数据又加回来。
 */
import { nowStr, saveDb } from '../core';

const VERSION = 1;
const daysAgo = (d, h = 9) => nowStr(new Date(Date.now() - d * 86400000 - h * 3600000));

/* ───────── 密钥占位 ───────── */

const SECRET_WORDS = ['api_key', 'apikey', 'secret', 'token', 'password', 'private_key', 'signature_key', 'access_key'];

/** 字段 / 参数编码是否属于密钥类（比页面上的判断更严格：包含即算） */
export function isSecretKey(key) {
  const k = String(key || '').toLowerCase();
  return SECRET_WORDS.some((w) => k.includes(w));
}

/** 占位值：带星号，与后端掩码格式一致（编辑弹窗聚焦时会据此清空输入框） */
export function placeholderFor(key) {
  return String(key || '').toLowerCase().includes('api_key') ? 'sk-demo-****' : 'demo-****';
}

/** 是否为掩码 / 占位值（含 * 或 •） */
export function isMasked(v) {
  return /[*•]/.test(String(v == null ? '' : v));
}

/**
 * 处理将要保存的密钥值：掩码值表示“未修改”，沿用旧值；新输入的内容一律替换成占位值，绝不保存。
 * 返回 { value, replaced }。
 */
export function sanitizeSecret(key, next, prev) {
  if (next == null || next === '') return { value: next, replaced: false };
  if (isMasked(next)) return { value: prev != null && prev !== '' ? prev : placeholderFor(key), replaced: false };
  return { value: placeholderFor(key), replaced: true };
}

/** 调用配置（configJson）里的密钥字段统一处理 */
export function sanitizeConfig(next, prev = {}) {
  const out = {};
  let replaced = false;
  Object.keys(next || {}).forEach((k) => {
    const v = next[k];
    if (isSecretKey(k) && typeof v === 'string') {
      const r = sanitizeSecret(k, v, prev[k]);
      out[k] = r.value;
      replaced = replaced || r.replaced;
    } else {
      out[k] = v;
    }
  });
  return { config: out, replaced };
}

/* ───────── 演示数据 ───────── */

// 补充的演示账号（mobile 用 138 0000 00xx 演示号段）
const EXTRA_USERS = [
  ['demo-u-2001', 'demo_lin', '+8613800000011', 1, 33, 2],
  ['demo-u-2002', 'demo_zhou', '+8613800000012', 1, 30, 1],
  ['demo-u-2003', 'demo_wu', '+8613800000013', 1, 27, 0],
  ['demo-u-2004', 'demo_zheng', '+8613800000014', 0, 25, 1],
  ['demo-u-2005', 'demo_wang', '+8613800000015', 1, 22, 3],
  ['demo-u-2006', 'demo_feng', '+8613800000016', 1, 16, 0],
  ['demo-u-2007', 'demo_chen', '+8613800000017', 1, 12, 1],
  ['demo-u-2008', 'demo_chu', '+8613800000018', 1, 7, 0],
  ['demo-u-2009', 'demo_wei', '+8613800000019', 0, 5, 0],
  ['demo-u-2010', 'demo_jiang', '+8613800000020', 1, 2, 1],
].map(([id, username, mobile, status, d, deviceCount]) => ({
  id, username, superAdmin: 0, status, mobile, createDate: daysAgo(d), deviceCount,
}));

const F = (key, label, type = 'string', def = '') => ({ key, label, type, default: def });
const P = (id, modelType, providerCode, name, fields, sort) => ({
  id, modelType, providerCode, name, fields: JSON.stringify(fields), sort, createDate: daysAgo(90), updateDate: daysAgo(30),
});

// 模型供应器（字段定义）；Plugin 类型的供应器来自 db.plugins，见 ensureAdminData
const PROVIDERS = [
  P('SYSTEM_VAD_SileroVAD', 'VAD', 'silero', 'SileroVAD 语音活动检测', [
    F('threshold', '检测阈值', 'number', '0.5'), F('model_dir', '模型目录', 'string', 'models/snakers4_silero-vad'),
    F('min_silence_duration_ms', '最小静音时长（毫秒）', 'number', '700')], 1),
  P('SYSTEM_ASR_FunASR', 'ASR', 'fun_local', 'FunASR 本地识别', [
    F('model_dir', '模型目录', 'string', 'models/SenseVoiceSmall'), F('output_dir', '输出目录', 'string', 'tmp/')], 1),
  P('SYSTEM_ASR_Qwen3Realtime', 'ASR', 'qwen3_asr_flash', '通义千问实时语音识别', [
    F('base_url', '服务地址'), F('model_name', '模型名称'), F('api_key', 'API 密钥')], 2),
  P('SYSTEM_ASR_DoubaoStream', 'ASR', 'doubao_stream', '火山引擎流式语音识别', [
    F('appid', '应用 ID'), F('cluster', '集群'), F('access_token', '访问令牌'), F('output_dir', '输出目录', 'string', 'tmp/')], 3),
  P('SYSTEM_LLM_openai', 'LLM', 'openai', 'OpenAI 兼容接口', [
    F('base_url', '接口地址'), F('model_name', '模型名称'), F('api_key', 'API 密钥'),
    F('temperature', '温度', 'number', '0.7'), F('max_tokens', '最大输出长度', 'number', '500'), F('top_p', 'top_p', 'number', '1')], 1),
  P('SYSTEM_LLM_ollama', 'LLM', 'ollama', 'Ollama 本地模型', [F('base_url', '服务地址'), F('model_name', '模型名称')], 2),
  P('SYSTEM_LLM_dify', 'LLM', 'dify', 'Dify 应用', [F('base_url', '接口地址'), F('api_key', 'API 密钥'), F('mode', '对话模式', 'string', 'chat-messages')], 3),
  P('SYSTEM_VLLM_openai', 'VLLM', 'openai', 'OpenAI 兼容视觉接口', [F('base_url', '接口地址'), F('model_name', '模型名称'), F('api_key', 'API 密钥')], 1),
  P('SYSTEM_Intent_function_call', 'Intent', 'function_call', '函数调用意图识别', [], 1),
  P('SYSTEM_Intent_intent_llm', 'Intent', 'intent_llm', '大模型意图识别', [F('llm', '使用的大模型 ID')], 2),
  P('SYSTEM_Intent_nointent', 'Intent', 'nointent', '不使用意图识别', [], 3),
  P('SYSTEM_Memory_mem_local_short', 'Memory', 'mem_local_short', '本地短期记忆', [F('llm', '总结用的大模型 ID')], 1),
  P('SYSTEM_Memory_mem0ai', 'Memory', 'mem0ai', 'Mem0 长期记忆', [F('api_key', 'API 密钥')], 2),
  P('SYSTEM_Memory_nomem', 'Memory', 'nomem', '无记忆', [], 3),
  P('SYSTEM_TTS_qwen', 'TTS', 'qwen_tts', '通义千问语音合成', [
    F('model', '模型名称'), F('voice', '默认音色'), F('api_key', 'API 密钥'), F('output_dir', '输出目录', 'string', 'tmp/')], 1),
  P('SYSTEM_TTS_edge', 'TTS', 'edge', 'Edge TTS', [F('voice', '默认音色'), F('output_dir', '输出目录', 'string', 'tmp/')], 2),
  P('SYSTEM_TTS_fishspeech', 'TTS', 'fishspeech', 'FishSpeech 声音克隆', [
    F('api_url', '接口地址'), F('api_key', 'API 密钥'), F('reference_id', '参考音色 ID'), F('output_dir', '输出目录', 'string', 'tmp/')], 3),
  P('SYSTEM_TTS_gpt_sovits_v2', 'TTS', 'gpt_sovits_v2', 'GPT-SoVITS v2', [
    F('url', '接口地址'), F('text_lang', '文本语言', 'string', 'zh'), F('ref_audio_path', '参考音频路径'), F('prompt_text', '参考文本'),
    F('output_dir', '输出目录', 'string', 'tmp/')], 4),
  P('SYSTEM_RAG_ragflow', 'RAG', 'ragflow', 'RAGFlow 知识库', [F('base_url', '接口地址'), F('api_key', 'API 密钥')], 1),
];

// 已有模型（seed/core.js）的调用配置与说明
const MODEL_EXTRAS = {
  VAD_SileroVAD: { type: 'silero', threshold: '0.5', model_dir: 'models/snakers4_silero-vad', min_silence_duration_ms: '700' },
  ASR_Qwen3ASRRealtime: { type: 'qwen3_asr_flash', base_url: 'wss://asr.demo.example/api-ws/v1/realtime', model_name: 'qwen3-asr-flash-realtime', api_key: 'sk-demo-****' },
  ASR_FunASR: { type: 'fun_local', model_dir: 'models/SenseVoiceSmall', output_dir: 'tmp/' },
  LLM_QwenPlusOfficial: { type: 'openai', base_url: 'https://llm.demo.example/compatible-mode/v1', model_name: 'qwen-plus', api_key: 'sk-demo-****', temperature: '0.7', max_tokens: '500', top_p: '1' },
  LLM_QwenTurbo: { type: 'openai', base_url: 'https://llm.demo.example/compatible-mode/v1', model_name: 'qwen-turbo', api_key: 'sk-demo-****', temperature: '0.7', max_tokens: '500', top_p: '1' },
  VLLM_QwenVLVLLM: { type: 'openai', base_url: 'https://llm.demo.example/compatible-mode/v1', model_name: 'qwen-vl-plus', api_key: 'sk-demo-****' },
  Intent_function_call: { type: 'function_call' },
  Intent_nointent: { type: 'nointent' },
  Memory_mem_local_short: { type: 'mem_local_short', llm: 'LLM_QwenTurbo' },
  Memory_bailian: { type: 'mem0ai', api_key: 'demo-****' },
  Memory_nomem: { type: 'nomem' },
  TTS_QwenAudioTTSPlus: { type: 'qwen_tts', model: 'qwen-tts', voice: 'Cherry', api_key: 'sk-demo-****', output_dir: 'tmp/' },
  TTS_EdgeTTS: { type: 'edge', voice: 'zh-CN-XiaoxiaoNeural', output_dir: 'tmp/' },
};

// 补充模型：只用于管理页演示（未被任何智能体引用）
const EXTRA_MODELS = [
  { id: 'LLM_OllamaLocal', modelType: 'LLM', modelCode: 'OllamaLocal', modelName: 'Ollama 本地模型（演示）', type: 'ollama', isDefault: 0, isEnabled: 0, sort: 3,
    configJson: { type: 'ollama', base_url: 'http://ollama.demo.example:11434', model_name: 'qwen2.5:7b' } },
  { id: 'LLM_DifyApp', modelType: 'LLM', modelCode: 'DifyApp', modelName: 'Dify 应用（演示）', type: 'dify', isDefault: 0, isEnabled: 1, sort: 4,
    configJson: { type: 'dify', base_url: 'https://dify.demo.example/v1', api_key: 'demo-****', mode: 'chat-messages' } },
  { id: 'Intent_intent_llm', modelType: 'Intent', modelCode: 'intent_llm', modelName: '大模型意图识别', isDefault: 0, isEnabled: 1, sort: 3,
    configJson: { type: 'intent_llm', llm: 'LLM_QwenTurbo' } },
  { id: 'TTS_FishSpeech', modelType: 'TTS', modelCode: 'FishSpeech', modelName: 'FishSpeech 声音克隆（演示）', isDefault: 0, isEnabled: 0, sort: 3,
    configJson: { type: 'fishspeech', api_url: 'http://tts.demo.example:8080/v1/tts', api_key: 'demo-****', reference_id: '', output_dir: 'tmp/' } },
  { id: 'RAG_RAGFlow', modelType: 'RAG', modelCode: 'RAGFlow', modelName: 'RAGFlow 知识库（演示）', isDefault: 1, isEnabled: 1, sort: 1,
    configJson: { type: 'ragflow', base_url: 'http://ragflow.demo.example', api_key: 'demo-****' } },
];

const EXTRA_VOICES = [
  { id: 'TTS_FishSpeech_0001', ttsModelId: 'TTS_FishSpeech', name: '克隆音色 A（演示）', ttsVoice: 'demo_clone_a', languages: '中文', sort: 1, remark: '',
    referenceAudio: 'config/assets/demo_reference_a.wav', referenceText: '今天天气不错，我们出去走走吧。', voiceDemo: '' },
  { id: 'TTS_FishSpeech_0002', ttsModelId: 'TTS_FishSpeech', name: '克隆音色 B（演示）', ttsVoice: 'demo_clone_b', languages: '中文', sort: 2, remark: '',
    referenceAudio: 'config/assets/demo_reference_b.wav', referenceText: '你好，很高兴认识你。', voiceDemo: '' },
];
// 已有音色补上试听地址（mock 模式下统一换成浏览器内生成的提示音，不会请求这些地址）
const VOICE_DEMOS = {
  TTS_QwenAudioTTSPlus_0001: '/demo-audio/qwen-cherry.mp3',
  TTS_QwenAudioTTSPlus_0002: '/demo-audio/qwen-ethan.mp3',
  TTS_EdgeTTS_0001: '/demo-audio/edge-xiaoxiao.mp3',
};

let pid = 100;
const PR = (paramCode, paramValue, valueType, remark) => ({ id: ++pid, paramCode, paramValue, valueType, remark, createDate: daysAgo(60), updateDate: daysAgo(10) });
const PARAMS = [
  PR('server.name', '小念控制台（演示）', 'string', '系统名称'),
  PR('server.websocket', 'ws://ws-a.demo.example:8000/xiaozhi/v1/;ws://ws-b.demo.example:8000/xiaozhi/v1/', 'string', 'WebSocket 服务地址，多个用英文分号分隔（演示地址）'),
  PR('server.ota', 'http://ota.demo.example:8002/xiaozhi/ota/', 'string', 'OTA 地址（演示地址）'),
  PR('server.secret', 'demo-****', 'string', '服务端通信密钥（演示占位值）'),
  PR('server.mqtt_gateway', 'mqtt.demo.example:1883', 'string', 'MQTT 网关地址（演示地址）'),
  PR('server.mqtt_signature_key', 'demo-****', 'string', 'MQTT 签名密钥（演示占位值）'),
  PR('server.allow_user_register', 'true', 'boolean', '是否允许管理员以外的人注册'),
  PR('server.enable_mobile_register', 'true', 'boolean', '是否开启手机号注册'),
  PR('server.fronted_url', 'http://console.demo.example', 'string', '控制台访问地址（演示地址）'),
  PR('server.beian_icp_num', 'null', 'string', 'ICP 备案号，填 null 表示不显示'),
  PR('server.beian_ga_num', 'null', 'string', '公安备案号，填 null 表示不显示'),
  PR('device_max_output_size', '0', 'number', '单台设备每天最多输出字数，0 表示不限制'),
  PR('wakeup_words', '你好小念;小念小念;嘿小念', 'array', '唤醒词，多个用英文分号分隔'),
  PR('plugins.get_weather.api_key', 'demo-****', 'string', '天气插件密钥（演示占位值）'),
  PR('plugins.get_weather.default_location', '杭州', 'string', '天气插件默认城市'),
  PR('memory_extract.enabled', 'false', 'string', '是否开启记忆提取'),
  PR('memory_extract.base_url', 'https://api.deepseek.com/v1', 'string', '记忆提取使用的接口地址'),
  PR('memory_extract.api_key', 'sk-demo-****', 'string', '记忆提取接口密钥（演示占位值）'),
  PR('memory_extract.model', 'deepseek-chat', 'string', '记忆提取使用的模型'),
  PR('habit_analyze.enabled', 'false', 'string', '是否开启习惯分析'),
  PR('habit_analyze.base_url', 'https://api.deepseek.com/v1', 'string', '习惯分析使用的接口地址'),
  PR('habit_analyze.api_key', 'sk-demo-****', 'string', '习惯分析接口密钥（演示占位值）'),
  PR('habit_analyze.model', 'deepseek-chat', 'string', '习惯分析使用的模型'),
];

const DICT_TYPE_NAMES = { FIRMWARE_TYPE: '固件类型', MOBILE_AREA: '手机区号' };
// 补充的固件类型（演示），让字典数据有足够的条目可以翻页
const EXTRA_FIRMWARE = [
  ['lichuang-dev', '立创开发板（演示）'], ['esp32-s3-touch-lcd', 'ESP32-S3 触摸屏（演示）'], ['atoms3r-echo-base', 'AtomS3R 语音底座（演示）'],
  ['xmini-c3', '迷你 C3（演示）'], ['esp-box-3', 'ESP-BOX-3（演示）'], ['magiclick-2p4', '魔点 2.4（演示）'],
  ['bread-compact-ml307', '面包板 4G 版（演示）'], ['kevin-box-2', 'Kevin Box 2（演示）'], ['m5stack-core-s3', 'M5Stack CoreS3（演示）'],
];

function nextNum(db) {
  db.seq = (db.seq || 1000) + 1;
  return db.seq;
}

/** 根据字典数据重建 db.dictByType（设备页、登录页按类型读取） */
export function syncDictByType(db) {
  const map = {};
  (db.dictTypes || []).forEach((t) => {
    map[t.dictType] = (db.dictData || []).filter((d) => d.dictTypeId === t.id)
      .sort((a, b) => (a.sort || 0) - (b.sort || 0))
      .map((d) => ({ key: d.dictValue, name: d.dictLabel }));
  });
  db.dictByType = map;
}

/** 把本文件的演示数据合并进数据库（幂等） */
export function ensureAdminData(db) {
  if (db.__xnAdmin === VERSION) return db;

  // 账号
  db.users = db.users || [];
  EXTRA_USERS.forEach((u) => { if (!db.users.some((x) => x.id === u.id)) db.users.push({ ...u }); });

  // 模型：补调用配置与说明字段
  db.models = db.models || [];
  db.models.forEach((m) => {
    if (!m.configJson) m.configJson = { ...(MODEL_EXTRAS[m.id] || { type: m.type || '' }) };
    if (m.docLink === undefined) m.docLink = '';
    if (m.remark === undefined) m.remark = '';
    if (!m.createDate) m.createDate = daysAgo(80);
  });
  EXTRA_MODELS.forEach((m) => {
    if (!db.models.some((x) => x.id === m.id)) db.models.push({ ...m, configJson: { ...m.configJson }, docLink: '', remark: '', createDate: daysAgo(20) });
  });

  // 音色
  db.ttsVoices = db.ttsVoices || [];
  db.ttsVoices.forEach((v) => {
    if (v.voiceDemo === undefined) v.voiceDemo = VOICE_DEMOS[v.id] || '';
    if (v.referenceAudio === undefined) v.referenceAudio = '';
    if (v.referenceText === undefined) v.referenceText = '';
  });
  EXTRA_VOICES.forEach((v) => { if (!db.ttsVoices.some((x) => x.id === v.id)) db.ttsVoices.push({ ...v }); });

  // 供应器（Plugin 类型来自插件列表，id 相同，增删改时同步 db.plugins）
  if (!Array.isArray(db.modelProviders)) {
    db.modelProviders = PROVIDERS.map((p) => ({ ...p }));
    (db.plugins || []).forEach((pl, i) => {
      db.modelProviders.push({ id: pl.id, modelType: 'Plugin', providerCode: pl.providerCode, name: pl.name, fields: pl.fields || '[]', sort: i + 1, createDate: daysAgo(90), updateDate: daysAgo(30) });
    });
  }

  // 参数
  if (!Array.isArray(db.params)) db.params = PARAMS.map((p) => ({ ...p }));

  // 字典：由已有的 dictByType 生成类型与数据，再补充演示固件类型
  if (!Array.isArray(db.dictTypes)) {
    db.dictTypes = [];
    db.dictData = [];
    const byType = db.dictByType || {};
    Object.keys(byType).forEach((type, ti) => {
      const typeId = nextNum(db);
      db.dictTypes.push({ id: typeId, dictType: type, dictName: DICT_TYPE_NAMES[type] || type, remark: '', sort: ti + 1, createDate: daysAgo(100), updateDate: daysAgo(30) });
      const rows = byType[type].map((x) => [x.key, x.name]).concat(type === 'FIRMWARE_TYPE' ? EXTRA_FIRMWARE : []);
      rows.forEach(([value, label], i) => {
        if (db.dictData.some((d) => d.dictTypeId === typeId && d.dictValue === value)) return;
        db.dictData.push({ id: nextNum(db), dictTypeId: typeId, dictLabel: label, dictValue: value, remark: '', sort: i + 1, createDate: daysAgo(100), updateDate: daysAgo(30) });
      });
    });
    syncDictByType(db);
  }

  db.__xnAdmin = VERSION;
  saveDb();
  return db;
}
