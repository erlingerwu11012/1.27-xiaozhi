/**
 * 模型（/models/*）
 * - 角色配置与创建向导用到的只读选项（所有登录用户可用）：模型名称、LLM 列表、音色、插件；
 * - 管理员的模型配置：列表、新增 / 编辑 / 复制 / 删除、启用、默认模型、供应器（字段管理），见文件后半部分。
 */
import { route, ok, fail, includesText, requireAdmin, paginate, nowStr } from '../core';
import { ensureAdminData, isSecretKey, isMasked, placeholderFor, sanitizeConfig } from '../seed/admin';

route('GET', '/models/names', ({ query, db }) => ok(
  db.models.filter((m) => m.modelType === query.modelType && m.isEnabled === 1 && includesText(m.modelName, query.modelName))
    .sort((a, b) => (a.sort || 0) - (b.sort || 0))
    .map((m) => ({ id: m.id, modelName: m.modelName })),
));

route('GET', '/models/llm/names', ({ query, db }) => ok(
  db.models.filter((m) => m.modelType === 'LLM' && m.isEnabled === 1 && includesText(m.modelName, query.modelName))
    .map((m) => ({ id: m.id, modelName: m.modelName, type: m.type || 'openai' })),
));

route('GET', '/models/:modelId/voices', ({ params, query, db }) => {
  if (!db.models.some((m) => m.id === params.modelId)) return fail('模型不存在');
  return ok(db.ttsVoices.filter((v) => v.ttsModelId === params.modelId && includesText(v.name, query.voiceName))
    .sort((a, b) => (a.sort || 0) - (b.sort || 0))
    .map((v) => ({ id: v.id, name: v.name, languages: v.languages, voiceDemo: v.voiceDemo || '' })));
});

route('GET', '/models/provider/plugin/names', ({ db }) => ok(db.plugins.map((p) => ({ ...p }))));

/* ───────── 管理员：模型配置、供应器 ───────── */
// 以下接口仅管理员可用。调用配置里的密钥字段只保存占位值（sk-demo-****），新输入的密钥不会被保存。

const TYPE_CANON = { vad: 'VAD', asr: 'ASR', llm: 'LLM', vllm: 'VLLM', intent: 'Intent', tts: 'TTS', memory: 'Memory', rag: 'RAG', plugin: 'Plugin' };
const canonType = (t) => TYPE_CANON[String(t || '').toLowerCase()] || String(t || '');
const sameType = (a, b) => String(a || '').toLowerCase() === String(b || '').toLowerCase();
const SECRET_NOTE = '演示环境不保存密钥，已用占位值代替';

function adminGuard(user, db) {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensureAdminData(db);
  return null;
}

/** 返回给页面的模型（调用配置里的密钥字段保持掩码） */
function modelOut(m) {
  const cfg = {};
  Object.keys(m.configJson || {}).forEach((k) => {
    const v = m.configJson[k];
    cfg[k] = isSecretKey(k) && typeof v === 'string' && v && !isMasked(v) ? placeholderFor(k) : v;
  });
  return {
    id: m.id, modelType: m.modelType, modelCode: m.modelCode, modelName: m.modelName,
    isDefault: m.isDefault, isEnabled: m.isEnabled, configJson: cfg,
    docLink: m.docLink || '', remark: m.remark || '', sort: m.sort || 0,
    createDate: m.createDate || '', updateDate: m.updateDate || '',
  };
}

function agentsUsing(db, modelId) {
  const keys = ['asrModelId', 'vadModelId', 'llmModelId', 'vllmModelId', 'ttsModelId', 'memModelId', 'intentModelId'];
  return (db.agents || []).filter((a) => keys.some((k) => a[k] === modelId));
}

function findProvider(db, modelType, providerCode) {
  return db.modelProviders.find((p) => sameType(p.modelType, modelType) && p.providerCode === providerCode);
}

route('GET', '/models/list', ({ query, user, db, scenario }) => {
  const denied = adminGuard(user, db); if (denied) return denied;
  if (scenario.data === 'empty') return ok({ list: [], total: 0 });
  const list = db.models
    .filter((m) => sameType(m.modelType, query.modelType) && includesText(m.modelName, query.modelName))
    .slice().sort((a, b) => (a.sort || 0) - (b.sort || 0))
    .map(modelOut);
  return ok(paginate(list, query.page, query.limit));
});

route('GET', '/models/:modelType/provideTypes', ({ params, user, db, scenario }) => {
  const denied = adminGuard(user, db); if (denied) return denied;
  if (scenario.data === 'empty') return ok([]);
  return ok(db.modelProviders.filter((p) => sameType(p.modelType, params.modelType))
    .slice().sort((a, b) => (a.sort || 0) - (b.sort || 0)).map((p) => ({ ...p })));
});

route('GET', '/models/:id', ({ params, user, db }) => {
  const denied = adminGuard(user, db); if (denied) return denied;
  const m = db.models.find((x) => x.id === params.id);
  return m ? ok(modelOut(m)) : fail('模型配置不存在或已被删除');
});

route('POST', '/models/:modelType/:provideCode', ({ params, body, user, db }) => {
  const denied = adminGuard(user, db); if (denied) return denied;
  const modelType = canonType(params.modelType);
  if (!findProvider(db, modelType, params.provideCode)) return fail('供应器不存在，请先在“字段管理”中添加');
  const id = String(body.id || '').trim() || `${modelType}_${Date.now().toString(36)}`;
  if (db.models.some((m) => m.id === id)) return fail(`模型 ID ${id} 已存在`);
  if (!String(body.modelName || '').trim()) return fail('请输入模型名称');
  const { config, replaced } = sanitizeConfig({ ...(body.configJson || {}), type: params.provideCode });
  // 新增时不改变本类别现有的默认模型；本类别还没有默认模型时才设为默认（待确认，见集成文档）
  const hasDefault = db.models.some((m) => m.modelType === modelType && m.isDefault === 1);
  db.models.push({
    id, modelType, modelCode: body.modelCode || '', modelName: String(body.modelName).trim(),
    isDefault: hasDefault ? 0 : 1, isEnabled: Number(body.isEnabled) === 1 ? 1 : 0,
    configJson: config, docLink: body.docLink || '', remark: body.remark || '', sort: Number(body.sort) || 0,
    type: modelType === 'LLM' ? params.provideCode : undefined,
    createDate: nowStr(), updateDate: nowStr(),
  });
  return ok(null, replaced ? SECRET_NOTE : 'success');
});

route('PUT', '/models/:modelType/:provideCode/:id', ({ params, body, user, db }) => {
  const denied = adminGuard(user, db); if (denied) return denied;
  const m = db.models.find((x) => x.id === params.id);
  if (!m) return fail('模型配置不存在或已被删除');
  if (!findProvider(db, m.modelType, params.provideCode)) return fail('供应器不存在，请先在“字段管理”中添加');
  if (!String(body.modelName || '').trim()) return fail('请输入模型名称');
  const { config, replaced } = sanitizeConfig({ ...(body.configJson || {}), type: params.provideCode }, m.configJson || {});
  Object.assign(m, {
    modelCode: body.modelCode == null ? m.modelCode : body.modelCode,
    modelName: String(body.modelName).trim(),
    isEnabled: body.isEnabled == null ? m.isEnabled : (Number(body.isEnabled) === 1 ? 1 : 0),
    configJson: config, docLink: body.docLink || '', remark: body.remark || '',
    sort: Number(body.sort) || 0, updateDate: nowStr(),
  });
  if (m.modelType === 'LLM') m.type = params.provideCode;
  return ok(null, replaced ? SECRET_NOTE : 'success');
});

route('DELETE', '/models/:id', ({ params, user, db }) => {
  const denied = adminGuard(user, db); if (denied) return denied;
  const m = db.models.find((x) => x.id === params.id);
  if (!m) return fail('模型配置不存在或已被删除');
  if (m.isDefault === 1) return fail('这是本类别的默认模型，请先把其他模型设为默认再删除');
  const used = agentsUsing(db, m.id);
  if (used.length) return fail(`有 ${used.length} 个智能体正在使用该模型，请先在角色配置中更换`);
  db.models = db.models.filter((x) => x.id !== m.id);
  if (m.modelType === 'TTS') db.ttsVoices = db.ttsVoices.filter((v) => v.ttsModelId !== m.id);
  return ok(null);
});

route('PUT', '/models/enable/:id/:status', ({ params, user, db }) => {
  const denied = adminGuard(user, db); if (denied) return denied;
  const m = db.models.find((x) => x.id === params.id);
  if (!m) return fail('模型配置不存在或已被删除');
  m.isEnabled = Number(params.status) === 1 ? 1 : 0;
  m.updateDate = nowStr();
  return ok(null);
});

route('PUT', '/models/default/:id', ({ params, user, db }) => {
  const denied = adminGuard(user, db); if (denied) return denied;
  const m = db.models.find((x) => x.id === params.id);
  if (!m) return fail('模型配置不存在或已被删除');
  db.models.forEach((x) => { if (x.modelType === m.modelType) x.isDefault = x.id === m.id ? 1 : 0; });
  return ok(null);
});

/* 供应器（字段管理）。fields 以 JSON 字符串保存，与页面 JSON.parse(item.fields) 的读取方式一致 */

function cleanFields(raw) {
  let arr = raw;
  if (typeof raw === 'string') { try { arr = JSON.parse(raw); } catch (e) { return null; } }
  if (!Array.isArray(arr)) return null;
  return arr.map((f) => {
    const def = f.default == null ? '' : f.default;
    return { key: String(f.key || ''), label: String(f.label || ''), type: f.type || 'string', default: isSecretKey(f.key) && def && !isMasked(def) ? placeholderFor(f.key) : def };
  });
}

function syncPlugin(db, p, removed = false) {
  if (p.modelType !== 'Plugin') return;
  db.plugins = (db.plugins || []).filter((x) => x.id !== p.id);
  if (!removed) db.plugins.push({ id: p.id, name: p.name, providerCode: p.providerCode, fields: p.fields });
}

function checkProvider(body, db) {
  if (!body.modelType) return '请选择类别';
  if (!String(body.providerCode || '').trim()) return '请输入供应器编码';
  if (!String(body.name || '').trim()) return '请输入供应器名称';
  if (db.modelProviders.some((p) => p.modelType === body.modelType && p.providerCode === String(body.providerCode).trim() && String(p.id) !== String(body.id || ''))) {
    return '该类别下已有相同编码的供应器';
  }
  return '';
}

route('GET', '/models/provider', ({ query, user, db, scenario }) => {
  const denied = adminGuard(user, db); if (denied) return denied;
  if (scenario.data === 'empty') return ok({ list: [], total: 0 });
  const order = ['VAD', 'ASR', 'LLM', 'VLLM', 'Intent', 'Memory', 'TTS', 'RAG', 'Plugin'];
  const list = db.modelProviders
    .filter((p) => (!query.modelType || p.modelType === query.modelType) && (includesText(p.name, query.name) || includesText(p.providerCode, query.name)))
    .slice().sort((a, b) => (order.indexOf(a.modelType) - order.indexOf(b.modelType)) || ((a.sort || 0) - (b.sort || 0)))
    .map((p) => ({ ...p }));
  return ok(paginate(list, query.page, query.limit));
});

route('POST', '/models/provider', ({ body, user, db }) => {
  const denied = adminGuard(user, db); if (denied) return denied;
  const err = checkProvider(body, db); if (err) return fail(err);
  const fields = cleanFields(body.fields); if (!fields) return fail('字段配置格式不正确');
  const p = {
    id: `${body.modelType}_${String(body.providerCode).trim()}_${Date.now().toString(36)}`, modelType: body.modelType,
    providerCode: String(body.providerCode).trim(), name: String(body.name).trim(), fields: JSON.stringify(fields),
    sort: Number(body.sort) || 0, createDate: nowStr(), updateDate: nowStr(),
  };
  db.modelProviders.push(p);
  syncPlugin(db, p);
  return ok(null);
});

route('PUT', '/models/provider', ({ body, user, db }) => {
  const denied = adminGuard(user, db); if (denied) return denied;
  const p = db.modelProviders.find((x) => String(x.id) === String(body.id));
  if (!p) return fail('供应器不存在或已被删除');
  const err = checkProvider(body, db); if (err) return fail(err);
  const fields = cleanFields(body.fields); if (!fields) return fail('字段配置格式不正确');
  const before = { modelType: p.modelType, providerCode: p.providerCode };
  const nextCode = String(body.providerCode).trim();
  if ((before.modelType !== body.modelType || before.providerCode !== nextCode)
    && db.models.some((m) => sameType(m.modelType, before.modelType) && m.configJson && m.configJson.type === before.providerCode)) {
    return fail('已有模型在使用这个供应器，不能修改类别或编码');
  }
  if (before.modelType === 'Plugin' && body.modelType !== 'Plugin') syncPlugin(db, p, true);
  Object.assign(p, { modelType: body.modelType, providerCode: nextCode, name: String(body.name).trim(), fields: JSON.stringify(fields), sort: Number(body.sort) || 0, updateDate: nowStr() });
  syncPlugin(db, p);
  return ok(null);
});

route('POST', '/models/provider/delete', ({ body, user, db }) => {
  const denied = adminGuard(user, db); if (denied) return denied;
  const ids = (Array.isArray(body) ? body : []).map(String);
  const targets = db.modelProviders.filter((p) => ids.includes(String(p.id)));
  if (!targets.length) return fail('请选择要删除的供应器');
  const inUse = targets.filter((p) => db.models.some((m) => sameType(m.modelType, p.modelType) && m.configJson && m.configJson.type === p.providerCode)
    || (p.modelType === 'Plugin' && (db.agents || []).some((a) => (a.functions || []).some((f) => f.pluginId === p.id))));
  if (inUse.length) return fail(`${inUse.map((p) => p.name).join('、')} 正在被模型或智能体使用，不能删除`);
  db.modelProviders = db.modelProviders.filter((p) => !ids.includes(String(p.id)));
  targets.forEach((p) => syncPlugin(db, p, true));
  return ok(null);
});
