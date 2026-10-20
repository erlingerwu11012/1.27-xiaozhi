/**
 * 音色管理（/ttsVoice）—— 模型配置页 TTS 模型的“音色管理”。仅管理员。数据在 db.ttsVoices，
 * 与角色配置读取的 /models/:modelId/voices 同源，所以这里的改动会出现在角色配置的音色列表里。
 * 试听地址只保存文本；mock 模式下页面播放的是浏览器内生成的提示音（src/utils/media.js）。
 */
import { route, ok, fail, requireAdmin, paginate, includesText } from '../core';
import { ensureAdminData } from '../seed/admin';

function guard(user, db) {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensureAdminData(db);
  return null;
}

function voiceOut(v) {
  return {
    id: v.id, ttsModelId: v.ttsModelId, name: v.name, ttsVoice: v.ttsVoice, languages: v.languages || '',
    remark: v.remark || '', referenceAudio: v.referenceAudio || '', referenceText: v.referenceText || '',
    voiceDemo: v.voiceDemo || '', sort: v.sort || 0,
  };
}

function check(body, db, id) {
  if (!db.models.some((m) => m.id === body.ttsModelId && m.modelType === 'TTS')) return 'TTS 模型不存在，请刷新后重试';
  if (!String(body.ttsVoice || '').trim() || !String(body.name || '').trim() || !String(body.languages || '').trim()) return '音色编码、音色名称和语言类型都必须填写';
  if (db.ttsVoices.some((v) => v.ttsModelId === body.ttsModelId && v.ttsVoice === String(body.ttsVoice).trim() && v.id !== id)) return '该模型下已有相同编码的音色';
  return '';
}

route('GET', '/ttsVoice', ({ query, user, db, scenario }) => {
  const denied = guard(user, db); if (denied) return denied;
  if (scenario.data === 'empty') return ok({ list: [], total: 0 });
  const list = db.ttsVoices
    .filter((v) => v.ttsModelId === query.ttsModelId && includesText(v.name, query.name))
    .slice().sort((a, b) => (a.sort || 0) - (b.sort || 0))
    .map(voiceOut);
  return ok(paginate(list, query.page, query.limit));
});

route('POST', '/ttsVoice', ({ body, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const err = check(body, db, null); if (err) return fail(err);
  db.seq = (db.seq || 1000) + 1;
  db.ttsVoices.push({
    id: `${body.ttsModelId}_${db.seq}`, ttsModelId: body.ttsModelId, name: String(body.name).trim(), ttsVoice: String(body.ttsVoice).trim(),
    languages: String(body.languages).trim(), remark: body.remark || '', referenceAudio: body.referenceAudio || '',
    referenceText: body.referenceText || '', voiceDemo: body.voiceDemo || '', sort: Number(body.sort) || 0,
  });
  return ok(null);
});

route('PUT', '/ttsVoice/:id', ({ params, body, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const v = db.ttsVoices.find((x) => x.id === params.id);
  if (!v) return fail('音色不存在或已被删除');
  const err = check({ ...body, ttsModelId: body.ttsModelId || v.ttsModelId }, db, v.id); if (err) return fail(err);
  Object.assign(v, {
    name: String(body.name).trim(), ttsVoice: String(body.ttsVoice).trim(), languages: String(body.languages).trim(),
    remark: body.remark || '', voiceDemo: body.voiceDemo || '',
    referenceAudio: body.referenceAudio == null ? v.referenceAudio : body.referenceAudio,
    referenceText: body.referenceText == null ? v.referenceText : body.referenceText,
  });
  return ok(null);
});

route('POST', '/ttsVoice/delete', ({ body, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const list = (Array.isArray(body) ? body : []).map(String);
  if (!list.length) return fail('请选择要删除的音色');
  const used = (db.agents || []).filter((a) => list.includes(String(a.ttsVoiceId)));
  if (used.length) return fail(`有 ${used.length} 个智能体正在使用所选音色，请先在角色配置中更换`);
  db.ttsVoices = db.ttsVoices.filter((v) => !list.includes(String(v.id)));
  return ok(null);
});
