/**
 * 智能体（/agent/*）—— 除基础增删改查（handlers/agent.js）以外的接口：
 * 默认角色模板、会话列表与聊天记录（含语音回放与下载）、MCP 接入点、声纹，以及创建向导里的克隆音色试听。
 *
 * 响应结构按调用方实际读取的字段编写：
 * - ChatHistoryDialog：res.data.data.list（会话）、res.data.data（消息数组 / 下载 uuid / 音频下载 id）
 * - AgentTemplateManagement：res.data.data.list / res.data.data.total
 * - TemplateQuickConfig：res.data.data（模板对象 / 模板数组）
 * - VoicePrintDialog：getRecentlyFiftyByAgentId → res.data.data 为 [{ audioId, content }]；getContentByAudioId → res.data.data 为文字
 * - VoicePrint / UnifiedUserManagement：只读 code，列表读 data 数组
 * - FunctionDialog：res.data.data 为工具名称数组
 */
import { route, ok, fail, requireAdmin, nextId, nowStr, paginate, includesText, clone } from '../core';
import { findOwnAgent } from './agent';
import { buildAgentExtraSeed } from '../seed/agent-extra';

const KEYS = ['agentChats', 'agentTemplates', 'voicePrints'];
/** 浏览器里已有旧版演示数据库（本模块上线前生成）时，补上缺少的集合 */
function ensure(db) {
  if (KEYS.every((k) => db[k])) return db;
  const fresh = buildAgentExtraSeed();
  KEYS.forEach((k) => { if (!db[k]) db[k] = fresh[k]; });
  return db;
}

/* 一次性的下载 / 播放凭证（只在内存里，刷新即失效，与真实接口“先换取临时 id”的流程一致） */
const tickets = new Map();
function ticket(payload) {
  const id = `demo-${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`;
  tickets.set(id, payload);
  return id;
}

/* ───────── 默认角色模板（管理员） ───────── */

const TEMPLATE_FIELDS = ['agentCode', 'agentName', 'systemPrompt', 'sort', 'asrModelId', 'vadModelId', 'llmModelId', 'vllmModelId',
  'ttsModelId', 'ttsVoiceId', 'memModelId', 'intentModelId', 'functions', 'chatHistoryConf', 'summaryMemory', 'langCode', 'language'];

const sortedTemplates = (db) => ensure(db).agentTemplates.slice().sort((a, b) => (Number(a.sort) || 0) - (Number(b.sort) || 0));

// 全部模板（新建模板时用来计算下一个排序号；普通用户也可读取，见集成文档“待确认”）
route('GET', '/agent/template', ({ db, scenario }) => {
  if (scenario.data === 'empty') return ok([]);
  return ok(clone(sortedTemplates(db)));
});

route('GET', '/agent/template/page', ({ db, user, query, scenario }) => {
  const denied = requireAdmin(user); if (denied) return denied;
  if (scenario.data === 'empty') return ok({ list: [], total: 0 });
  const rows = sortedTemplates(db).filter((t) => includesText(t.agentName, query.agentName));
  const { list, total } = paginate(rows, query.page, query.limit);
  return ok({ list: clone(list), total });
});

route('GET', '/agent/template/:templateId', ({ db, user, params }) => {
  const denied = requireAdmin(user); if (denied) return denied;
  const t = ensure(db).agentTemplates.find((x) => x.id === params.templateId);
  return t ? ok(clone(t)) : fail('模板不存在或已被删除');
});

function checkTemplate(body) {
  const name = String(body.agentName || '').trim();
  if (!name) return '模板名称不能为空';
  if (name.length > 64) return '模板名称不能超过 64 个字';
  if (String(body.systemPrompt || '').length > 2000) return '角色介绍不能超过 2000 个字';
  return '';
}

route('POST', '/agent/template', ({ db, user, body }) => {
  const denied = requireAdmin(user); if (denied) return denied;
  const err = checkTemplate(body); if (err) return fail(err);
  const t = { id: `demo-t-${nextId()}`, functions: [] };
  TEMPLATE_FIELDS.forEach((k) => { if (body[k] !== undefined) t[k] = body[k]; });
  t.agentName = String(body.agentName).trim();
  ensure(db).agentTemplates.push(t);
  return ok(null);
});

route('PUT', '/agent/template', ({ db, user, body }) => {
  const denied = requireAdmin(user); if (denied) return denied;
  const t = ensure(db).agentTemplates.find((x) => x.id === body.id);
  if (!t) return fail('模板不存在或已被删除');
  const err = checkTemplate(body); if (err) return fail(err);
  TEMPLATE_FIELDS.forEach((k) => { if (body[k] !== undefined) t[k] = body[k]; });
  t.agentName = String(body.agentName).trim();
  return ok(null);
});

route('DELETE', '/agent/template/:id', ({ db, user, params }) => {
  const denied = requireAdmin(user); if (denied) return denied;
  ensure(db);
  if (!db.agentTemplates.some((x) => x.id === params.id)) return fail('模板不存在或已被删除');
  db.agentTemplates = db.agentTemplates.filter((x) => x.id !== params.id);
  return ok(null);
});

route('POST', '/agent/template/batch-remove', ({ db, user, body }) => {
  const denied = requireAdmin(user); if (denied) return denied;
  const ids = Array.isArray(body) ? body.map(String) : [];
  if (!ids.length) return fail('请选择要删除的模板');
  ensure(db).agentTemplates = db.agentTemplates.filter((x) => !ids.includes(x.id));
  return ok(null);
});

/* ───────── 会话与聊天记录 ───────── */

function chatsOf(db, user, agentId) {
  const agent = findOwnAgent(db, user, agentId);
  if (!agent) return null;
  return ensure(db).agentChats[agent.id] || [];
}

// 会话列表：{ list: [{ sessionId, createdAt, chatCount }], total }，按时间从新到旧
route('GET', '/agent/:agentId/sessions', ({ db, user, params, query, scenario }) => {
  const sessions = chatsOf(db, user, params.agentId);
  if (!sessions) return fail('智能体不存在或无权查看');
  if (scenario.data === 'empty') return ok({ list: [], total: 0 });
  const rows = sessions.map((s) => ({ sessionId: s.sessionId, createdAt: s.createdAt, chatCount: s.messages.length }));
  const { list, total } = paginate(rows, query.page, query.limit || 20);
  return ok({ list, total });
});

// 某个会话的消息：[{ id, chatType, content, audioId, macAddress, createdAt }]，按时间从早到晚
route('GET', '/agent/:agentId/chat-history/:sessionId', ({ db, user, params }) => {
  const sessions = chatsOf(db, user, params.agentId);
  if (!sessions) return fail('智能体不存在或无权查看');
  const s = sessions.find((x) => x.sessionId === params.sessionId);
  if (!s) return fail('会话不存在');
  return ok(clone(s.messages).reverse());
});

/** 当前账号可见的全部消息（用于按 audioId 查找） */
function ownMessages(db, user) {
  ensure(db);
  return Object.keys(db.agentChats)
    .filter((agentId) => findOwnAgent(db, user, agentId))
    .reduce((all, agentId) => all.concat(...db.agentChats[agentId].map((s) => s.messages)), []);
}

// 最近 50 条带语音的用户消息（声纹录入时选择音频用）：[{ audioId, content }]
route('GET', '/agent/:id/chat-history/user', ({ db, user, params, scenario }) => {
  const sessions = chatsOf(db, user, params.id);
  if (!sessions) return fail('智能体不存在或无权查看');
  if (scenario.data === 'empty') return ok([]);
  const rows = [];
  sessions.forEach((s) => s.messages.forEach((m) => { if (m.chatType === 1 && m.audioId) rows.push(m); }));
  return ok(rows.sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1)).slice(0, 50).map((m) => ({ audioId: m.audioId, content: m.content })));
});

// 注意：这里的 :id 是 audioId（与 VoicePrintDialog 的调用一致），返回该音频对应的文字
route('GET', '/agent/:id/chat-history/audio', ({ db, user, params }) => {
  const m = ownMessages(db, user).find((x) => x.audioId === params.id);
  return m ? ok(m.content) : fail('没有找到这段语音');
});

// 换取音频播放 id；前端随后用 /agent/play/{id} 播放（演示模式下由 utils/media.js 生成本地提示音，不访问该地址）
route('POST', '/agent/audio/:audioId', ({ db, user, params }) => {
  const m = ownMessages(db, user).find((x) => x.audioId === params.audioId);
  if (!m) return fail('没有找到这段语音');
  return ok(ticket({ audioId: params.audioId }));
});

// 换取聊天记录下载 uuid；前端随后打开 /agent/chat-history/download/{uuid}/current|previous（演示模式下在浏览器内生成文本）
route('POST', '/agent/chat-history/getDownloadUrl/:agentId/:sessionId', ({ db, user, params }) => {
  const sessions = chatsOf(db, user, params.agentId);
  if (!sessions) return fail('智能体不存在或无权查看');
  if (!sessions.some((s) => s.sessionId === params.sessionId)) return fail('会话不存在');
  return ok(ticket({ agentId: params.agentId, sessionId: params.sessionId }));
});

/* ───────── MCP 接入点 ───────── */

// 接入点地址：演示数据，仅占位（页面上没有展示该地址）
route('GET', '/agent/mcp/address/:agentId', ({ db, user, params }) => {
  const a = findOwnAgent(db, user, params.agentId);
  if (!a) return fail('智能体不存在或无权查看');
  return ok(`wss://mcp.demo.invalid/mcp/?token=demo-${a.id}`);
});

// 设备侧通过接入点上报的工具名称。演示：只有最近在线的“小念（演示）”上报了工具，其他智能体为空（显示“未连接”）
const DEMO_MCP_TOOLS = { 'demo-a-1': ['self.get_device_status', 'self.audio_speaker.set_volume', 'self.screen.set_brightness'] };
route('GET', '/agent/mcp/tools/:agentId', ({ db, user, params, scenario }) => {
  const a = findOwnAgent(db, user, params.agentId);
  if (!a) return fail('智能体不存在或无权查看');
  if (scenario.data === 'empty') return ok([]);
  return ok((DEMO_MCP_TOOLS[a.id] || []).slice());
});

/* ───────── 声纹 ───────── */

export function voicePrintRow(v) {
  return { id: v.id, agentId: v.agentId, audioId: v.audioId, sourceName: v.sourceName, introduce: v.introduce || '', userId: v.userId || null, createDate: v.createDate };
}
/** 当前账号的全部声纹（供“人员身份”等模块复用同一份演示数据） */
export function ownVoicePrints(db, user) {
  return ensure(db).voicePrints.filter((v) => findOwnAgent(db, user, v.agentId));
}

function checkVoicePrint(body) {
  if (!body.audioId) return '请选择一段语音作为声纹';
  if (!String(body.sourceName || '').trim()) return '请填写说话人姓名';
  if (String(body.introduce || '').length > 100) return '描述不能超过 100 个字';
  return '';
}

route('POST', '/agent/voice-print', ({ db, user, body }) => {
  const a = findOwnAgent(db, user, body.agentId);
  if (!a) return fail('智能体不存在或无权操作');
  const err = checkVoicePrint(body); if (err) return fail(err);
  if (!ownMessages(db, user).some((m) => m.audioId === body.audioId)) return fail('没有找到这段语音');
  ensure(db).voicePrints.push({
    id: `demo-vp-${nextId()}`, agentId: a.id, audioId: body.audioId, sourceName: String(body.sourceName).trim(),
    introduce: body.introduce || '', userId: body.userId || null, createDate: nowStr(),
  });
  return ok(null);
});

route('GET', '/agent/voice-print/list/:id', ({ db, user, params, scenario }) => {
  if (!findOwnAgent(db, user, params.id)) return fail('智能体不存在或无权查看');
  if (scenario.data === 'empty') return ok([]);
  return ok(ensure(db).voicePrints.filter((v) => v.agentId === params.id).map(voicePrintRow));
});

route('PUT', '/agent/voice-print', ({ db, user, body }) => {
  const v = ownVoicePrints(db, user).find((x) => x.id === body.id);
  if (!v) return fail('声纹不存在或无权操作');
  const err = checkVoicePrint({ ...v, ...body }); if (err) return fail(err);
  ['audioId', 'sourceName', 'introduce', 'userId'].forEach((k) => { if (body[k] !== undefined) v[k] = k === 'sourceName' ? String(body[k]).trim() : body[k]; });
  return ok(null);
});

route('DELETE', '/agent/voice-print/:id', ({ db, user, params }) => {
  const v = ownVoicePrints(db, user).find((x) => x.id === params.id);
  if (!v) return fail('声纹不存在或无权操作');
  db.voicePrints = db.voicePrints.filter((x) => x.id !== v.id);
  return ok(null);
});

/* ───────── 创建向导：克隆音色试听 ───────── */

// 换取克隆音色的试听 id；前端随后播放 /voiceClone/play/{id}（演示模式下播放本地提示音）
route('POST', '/voiceClone/audio/:id', ({ params }) => ok(ticket({ voiceId: params.id })));
