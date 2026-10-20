/**
 * 智能体（/agent/*）—— 基础部分：列表、新建、删除、读取与保存配置。
 * 会话、聊天记录、声纹、模板、MCP 等其余 /agent 接口在 handlers/agent-extra.js。
 */
import { route, ok, fail, nextId, nowStr } from '../core';

export function ownAgents(db, user) {
  return db.agents.filter((a) => a.userId === user.id);
}
export function findOwnAgent(db, user, agentId) {
  return db.agents.find((a) => a.id === agentId && (a.userId === user.id || user.superAdmin === 1));
}
const modelName = (db, id) => (db.models.find((m) => m.id === id) || {}).modelName || '';
const voiceName = (db, id) => (db.ttsVoices.find((v) => v.id === id) || {}).name || '';

/** /agent/list 的一行：与原页面读取的字段一致 */
export function agentListRow(db, a) {
  return {
    id: a.id,
    agentName: a.agentName,
    systemPrompt: a.systemPrompt,
    llmModelName: modelName(db, a.llmModelId),
    ttsModelName: modelName(db, a.ttsModelId),
    ttsVoiceName: voiceName(db, a.ttsVoiceId),
    memModelId: a.memModelId,
    deviceCount: db.devices.filter((d) => d.agentId === a.id).length,
    lastConnectedAt: a.lastConnectedAt,
    createdAt: a.createdAt,
  };
}

route('GET', '/agent/list', ({ db, user, scenario }) => {
  if (scenario.data === 'empty') return ok([]);
  return ok(ownAgents(db, user).sort((x, y) => (x.sort || 0) - (y.sort || 0)).map((a) => agentListRow(db, a)));
});

route('POST', '/agent', ({ body, db, user }) => {
  const name = String(body.agentName || '').trim();
  if (!name) return fail('智能体名称不能为空');
  const id = `demo-a-${nextId()}`;
  const defaults = (db.models || []).reduce((m, x) => { if (x.isDefault === 1 && !m[x.modelType]) m[x.modelType] = x.id; return m; }, {});
  db.agents.push({
    id, userId: user.id, agentCode: `AGT_${id.toUpperCase().replace(/-/g, '_')}`, agentName: name, deviceName: name, userNickname: '',
    asrModelId: defaults.ASR, vadModelId: defaults.VAD, llmModelId: defaults.LLM, vllmModelId: defaults.VLLM,
    ttsModelId: defaults.TTS, ttsVoiceId: (db.ttsVoices.find((v) => v.ttsModelId === defaults.TTS) || {}).id,
    memModelId: defaults.Memory, intentModelId: defaults.Intent, chatHistoryConf: 2, summaryMemory: '',
    langCode: 'zh_CN', language: '中文', sort: ownAgents(db, user).length + 1, systemPrompt: '', functions: [],
    createdAt: nowStr(), lastConnectedAt: null,
  });
  return ok(id);
});

route('DELETE', '/agent/:agentId', ({ params, db, user }) => {
  const a = findOwnAgent(db, user, params.agentId);
  if (!a) return fail('智能体不存在或无权操作');
  db.agents = db.agents.filter((x) => x.id !== a.id);
  db.devices = db.devices.filter((d) => d.agentId !== a.id);   // 删除智能体时其设备随之解除关联
  return ok(null);
});

route('GET', '/agent/:agentId', ({ params, db, user }) => {
  const a = findOwnAgent(db, user, params.agentId);
  if (!a) return fail('智能体未找到');
  const { userId, ...config } = a;
  return ok(config);
});

const EDITABLE = ['agentCode', 'agentName', 'deviceName', 'userNickname', 'asrModelId', 'vadModelId', 'llmModelId', 'vllmModelId',
  'ttsModelId', 'ttsVoiceId', 'chatHistoryConf', 'memModelId', 'intentModelId', 'systemPrompt', 'summaryMemory', 'langCode',
  'language', 'sort', 'functions'];

route('PUT', '/agent/:agentId', ({ params, body, db, user }) => {
  const a = findOwnAgent(db, user, params.agentId);
  if (!a) return fail('智能体未找到');
  if (body.agentName !== undefined && !String(body.agentName).trim()) return fail('智能体名称不能为空');
  EDITABLE.forEach((k) => { if (body[k] !== undefined) a[k] = body[k]; });
  return ok(null);
});
