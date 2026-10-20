/**
 * 官方语音（/official-tts/*）与管理员接口（/admin/official-tts/*）。
 * - 音色设计 / 复刻、配音任务都只更新本机演示数据；试听与下载的音频是浏览器内生成的提示音（toneWavBlob），不是真实合成结果。
 * - 复刻上传只记录文件名、大小与类型，不保存、不上传音频内容。
 * - 任务进度随轮询推进：queued →（约 2 秒）running →（约 7 秒）done；完成时按演示单价扣演示点数并写一条调用明细。
 * 响应字段按调用方读取的方式返回：页面读取 res.data.data（success 回调拿到的是完整响应）。
 */
import { route, ok, fail, blob, saveDb, nextId, clone, requireAdmin } from '../core';
import { toneWavBlob } from '../media';
import { buildOfficialTtsSeed } from '../seed/officialTts';
import '../seed/billing';

const VERIFIED = [
  { code: 'longanlingxi', name: '龙安灵汐' },
  { code: 'longanqian', name: '龙安千' },
];
const VOICE_READY_MS = 6000;
const JOB_RUN_MS = 2000;
const JOB_DONE_MS = 7000;

function ensure(db) {
  if (!db.ttsVoicesMine || !db.ttsJobs || !db.ttsAdmin) {
    const s = buildOfficialTtsSeed();
    Object.keys(s).forEach((k) => { if (!db[k]) db[k] = s[k]; });
    saveDb();
  }
  return db;
}

const mineVoices = (db, user) => db.ttsVoicesMine.filter((v) => v.userId === user.id && v.status !== 'deleted');
const findVoice = (db, user, id) => db.ttsVoicesMine.find((v) => String(v.id) === String(id) && v.userId === user.id && v.status !== 'deleted');
const findJob = (db, user, id) => db.ttsJobs.find((j) => String(j.id) === String(id) && (j.userId === user.id));

/** 对外的音色字段（OfficialTtsVoices / OfficialTtsVoiceLibrary / OfficialTtsDubbing 读取的字段） */
function voiceRow(v) {
  return {
    id: v.id, kind: v.kind, name: v.name, status: v.status, upstreamVoiceId: v.upstreamVoiceId,
    hasPreview: v.hasPreview, errorMsg: v.errorMsg || '', createdAt: v.createdAt,
  };
}
function jobRow(j) {
  return {
    id: j.id, jobType: j.jobType, status: j.status, voiceCode: j.voiceCode, synthesisText: j.synthesisText,
    requestJson: j.requestJson, errorMsg: j.errorMsg || '', createdAt: j.createdAt, finishedAt: j.finishedAt || null,
  };
}

function progressVoices(db) {
  const now = Date.now();
  db.ttsVoicesMine.forEach((v) => {
    if (v.status === 'processing' && now - new Date(v.createdAt).getTime() >= VOICE_READY_MS) {
      v.status = 'available';
      v.upstreamVoiceId = `demo-${v.kind}-voice-${String(v.id).padStart(4, '0')}`;
      v.hasPreview = v.kind === 'design';
    }
  });
}

function salePrice(db, operation) {
  const p = (db.ttsAdmin.prices || []).find((x) => x.priceKind === 'sale_points' && x.operation === operation && x.status === 'published' && x.lifecycleStatus === 'active');
  return p ? Number(p.amount) : 0;
}

/** 演示计费：按字符数 × 演示单价换算成点数（换算比例同样只是演示值） */
function estimatePoints(db, text) {
  const chars = Array.from(String(text || '')).length;
  return Number(Math.max(0.01, chars * salePrice(db, 'synthesize') * 100).toFixed(4));
}

function progressJobs(db) {
  const now = Date.now();
  db.ttsJobs.forEach((j) => {
    const age = now - new Date(j.createdAt).getTime();
    if (j.status === 'queued' && age >= JOB_RUN_MS) j.status = 'running';
    if (j.status === 'running' && age >= JOB_DONE_MS) {
      j.status = 'done';
      j.finishedAt = new Date().toISOString();
      j.charged = j.held;
      j.held = 0;
      j.state = 'settled';
      const acc = (db.accounts || {})[j.userId];
      if (acc) acc.balance = Number((Number(acc.balance || 0) - j.charged).toFixed(4));
      if (Array.isArray(db.payCalls)) {
        db.payCalls.unshift({
          id: `demo-call-tts-${j.id}`, userId: j.userId, createdAt: Math.floor(Date.now() / 1000), operation: 'tts', model: 'cosyvoice（演示）',
          points: j.charged, paidAmountCny: Number((j.charged * 0.01).toFixed(6)), legacyPoints: 0, reservedPoints: 0, state: 'settled',
          inputTokens: null, outputTokens: null, cachedTokens: null, units: Array.from(j.synthesisText || '').length, unit: 'weighted_character',
        });
      }
    }
  });
}

function voiceTone(db, code) {
  const v = db.ttsVoicesMine.find((x) => x.upstreamVoiceId === code);
  if (v && v.tone) return v.tone;
  return code === 'longanqian' ? 262 : 349;
}

/* ───────── 用户侧 ───────── */

route('GET', '/official-tts/capabilities', ({ db }) => {
  ensure(db);
  const op = { callable: true, priced: true };
  return ok({
    accessStatus: 'ready', accessStatusText: '', enhancedEnabled: true, pricingStatus: 'priced', customerCallable: true,
    operations: { synthesize: { ...op }, design: { ...op }, clone: { ...op } },
    verifiedVoices: clone(VERIFIED),
    formatsExport: ['wav', 'mp3', 'pcm', 'opus'],
    controlTags: ['sad', 'amazed', 'angry', 'excited', 'serious', 'laughing'],
    volume: { min: 0, max: 100, default: 50 },
    rate: { min: 0.5, max: 2, default: 1 },
  });
});

route('GET', '/official-tts/voices', ({ db, user, scenario }) => {
  ensure(db);
  progressVoices(db);
  saveDb();
  if (scenario.data === 'empty') return ok([]);
  return ok(mineVoices(db, user).sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt)).map(voiceRow));
});

route('POST', '/official-tts/voices', ({ db, user, body }) => {
  ensure(db);
  if (body.kind !== 'design') return fail('不支持的音色类型');
  const prompt = String(body.prompt || '').trim();
  if (!prompt) return fail('请先输入音色描述');
  const preview = String(body.previewText || '').trim();
  if (preview && Array.from(preview).length < 15) return fail('预览文本长度需大于等于 15 个字符');
  const v = {
    id: nextId(), userId: user.id, kind: 'design', name: String(body.name || prompt).slice(0, 24), prompt, previewText: preview,
    status: 'processing', upstreamVoiceId: null, hasPreview: false, errorMsg: '', createdAt: new Date().toISOString(), tone: 300 + Math.floor(Math.random() * 160),
  };
  db.ttsVoicesMine.push(v);
  return ok(voiceRow(v), '演示：已登记设计任务，几秒后生成演示音色');
});

route('POST', '/official-tts/assets', ({ db, user, body }) => {
  ensure(db);
  const file = body.file;
  if (!file || !file.__file) return fail('请先选择或录制音频');
  if (body.kind !== 'clone') return fail('不支持的素材类型');
  if (file.size > 20 * 1024 * 1024) return fail('音频文件过大，请上传 20 MB 以内的音频');
  const v = {
    id: nextId(), userId: user.id, kind: 'clone', name: String(body.name || '我的音色').slice(0, 32), status: 'processing',
    upstreamVoiceId: null, hasPreview: false, errorMsg: '', createdAt: new Date().toISOString(),
    file: { name: file.name, size: file.size, type: file.type }, tone: 280 + Math.floor(Math.random() * 120),
  };
  db.ttsVoicesMine.push(v);
  return ok({ assetId: `demo-asset-${v.id}`, voice: voiceRow(v) }, '演示：只记录了文件名和大小，音频没有上传');
});

route('PUT', '/official-tts/voices/:id', ({ db, user, params, body }) => {
  ensure(db);
  const v = findVoice(db, user, params.id);
  if (!v) return fail('音色不存在或已删除');
  const name = String(body.name || '').trim();
  if (!name) return fail('名称不能为空');
  if (Array.from(name).length > 32) return fail('名称不能超过 32 个字符');
  v.name = name;
  return ok(voiceRow(v));
});

route('DELETE', '/official-tts/voices/:id', ({ db, user, params }) => {
  ensure(db);
  const v = findVoice(db, user, params.id);
  if (!v) return fail('音色不存在或已删除');
  if (v.status === 'processing') return fail('音色仍在生成中，完成后再删除');
  v.status = 'deleted';
  return ok(null);
});

route('GET', '/official-tts/voices/:id/preview', ({ db, user, params }) => {
  ensure(db);
  const v = findVoice(db, user, params.id);
  if (!v) return fail('音色不存在或已删除');
  if (!v.hasPreview) return fail('该音色暂无试听音频');
  return blob(toneWavBlob(1.6, v.tone || 330));
});

/** 按需生成试听（真实接口会产生费用；演示只把 hasPreview 置为 true） */
route('POST', '/official-tts/voices/:id/preview', ({ db, user, params }) => {
  ensure(db);
  const v = findVoice(db, user, params.id);
  if (!v) return fail('音色不存在或已删除');
  if (v.status !== 'available') return fail('音色尚未就绪，暂时无法试听');
  v.hasPreview = true;
  return blob(toneWavBlob(1.6, v.tone || 330));
});

/** 页面目前没有调用；按接口定义实现：把音色记到智能体上（待确认真实行为） */
route('POST', '/official-tts/voices/:id/bind', ({ db, user, params, query }) => {
  ensure(db);
  const v = findVoice(db, user, params.id);
  if (!v) return fail('音色不存在或已删除');
  const agent = (db.agents || []).find((a) => a.id === query.agentId && a.userId === user.id);
  if (!agent) return fail('智能体不存在');
  if (v.status !== 'available') return fail('音色尚未就绪');
  agent.officialVoiceId = v.upstreamVoiceId;
  return ok(null, '演示：已把音色记到智能体上');
});

route('GET', '/official-tts/jobs', ({ db, user, scenario }) => {
  ensure(db);
  progressJobs(db);
  saveDb();
  if (scenario.data === 'empty') return ok([]);
  return ok(db.ttsJobs.filter((j) => j.userId === user.id && j.status !== 'deleted')
    .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt)).map(jobRow));
});

route('POST', '/official-tts/jobs', ({ db, user, body }) => {
  ensure(db);
  const text = String(body.text || '').trim();
  if (!text) return fail('请先输入要合成的文本');
  if (Array.from(text).length > 5000) return fail('文本过长，请分段合成');
  if (!body.voice) return fail('请先选择音色');
  const known = VERIFIED.some((v) => v.code === body.voice) || mineVoices(db, user).some((v) => v.upstreamVoiceId === body.voice);
  if (!known) return fail('音色不可用，请重新选择');
  const held = estimatePoints(db, text);
  const acc = (db.accounts || {})[user.id];
  if (acc && Number(acc.balance) < held) return fail('余额不足，请先充值');
  const j = {
    id: nextId(), userId: user.id, jobType: body.jobType || 'dubbing', status: 'queued', voiceCode: body.voice, synthesisText: text,
    requestJson: JSON.stringify(body), createdAt: new Date().toISOString(), finishedAt: null, charged: 0, held, state: 'reserved',
  };
  db.ttsJobs.push(j);
  return ok(jobRow(j), '演示：已提交配音任务，生成的是演示提示音');
});

route('POST', '/official-tts/jobs/:id/cancel', ({ db, user, params }) => {
  ensure(db);
  progressJobs(db);
  const j = findJob(db, user, params.id);
  if (!j) return fail('任务不存在');
  if (j.status !== 'queued' && j.status !== 'running') return fail('任务已结束，无法取消');
  j.status = 'canceled';
  j.finishedAt = new Date().toISOString();
  j.held = 0;
  j.state = 'released';
  return ok(jobRow(j), '演示：已取消，冻结的点数已释放');
});

route('DELETE', '/official-tts/jobs/:id', ({ db, user, params }) => {
  ensure(db);
  const j = findJob(db, user, params.id);
  if (!j) return fail('任务不存在');
  if (j.status === 'queued' || j.status === 'running') return fail('任务进行中，请先取消');
  j.status = 'deleted';
  return ok(null);
});

route('GET', '/official-tts/jobs/:id/download', ({ db, user, params }) => {
  ensure(db);
  progressJobs(db);
  const j = findJob(db, user, params.id);
  if (!j) return fail('任务不存在');
  if (j.status !== 'done') return fail('任务未完成，暂不可用');
  const secs = Math.min(6, 1 + Array.from(j.synthesisText || '').length * 0.06);
  return blob(toneWavBlob(secs, voiceTone(db, j.voiceCode)));
});

/* ───────── 管理员 ───────── */

route('GET', '/admin/official-tts/overview', ({ db, user, scenario }) => {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensure(db);
  const a = db.ttsAdmin;
  const empty = scenario.data === 'empty';
  return ok({
    enhancedFlag: a.enhancedFlag,
    allowUsers: a.allowUsers,
    voices: empty ? 0 : db.ttsVoicesMine.filter((v) => v.status !== 'deleted').length,
    jobs: empty ? 0 : db.ttsJobs.filter((j) => j.status !== 'deleted').length,
    uncertainLedgers: empty ? 0 : db.ttsJobs.filter((j) => j.state === 'manual_review').length,
    priceUnitHintSale: '售价单位：元 / 计量单位，系统按此换算为点数（演示数据）',
    priceUnitHintCost: '成本价只用于核算，不能当作售价（演示数据）',
    prices: empty ? [] : clone(a.prices).sort((x, y) => x.id - y.id),
  });
});

route('PUT', '/admin/official-tts/prices', ({ db, user, body }) => {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensure(db);
  const p = db.ttsAdmin.prices.find((x) => x.id === Number(body.id));
  if (!p) return fail('价格版本不存在');
  if (p.priceKind !== 'sale_points' || p.status !== 'draft') return fail('只能修改售价草稿；已发布版本请先新建草稿');
  const amount = body.amount;
  if (amount === null || amount === undefined || Number.isNaN(Number(amount))) return fail('请填写金额');
  if (Number(amount) <= 0) return fail('金额必须大于 0');
  p.amount = Number(amount);
  return ok(clone(p), '演示：草稿已保存，当前生效价未变');
});

route('POST', '/admin/official-tts/prices/draft-from', ({ db, user, body }) => {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensure(db);
  const src = db.ttsAdmin.prices.find((x) => x.id === Number(body.id));
  if (!src) return fail('价格版本不存在');
  if (src.priceKind !== 'sale_points') return fail('成本价不能用于新建售价草稿');
  if (db.ttsAdmin.prices.some((x) => x.operation === src.operation && x.priceKind === 'sale_points' && x.status === 'draft')) {
    return fail('该操作已有未发布的草稿，请先编辑或发布它');
  }
  const n = db.ttsAdmin.prices.filter((x) => x.operation === src.operation && x.priceKind === 'sale_points').length + 1;
  const p = { ...src, id: nextId(), status: 'draft', lifecycleStatus: 'draft', version: `演示价格 v${n}` };
  db.ttsAdmin.prices.push(p);
  return ok(clone(p));
});

route('POST', '/admin/official-tts/prices/publish', ({ db, user, body }) => {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensure(db);
  const p = db.ttsAdmin.prices.find((x) => x.id === Number(body.id));
  if (!p) return fail('价格版本不存在');
  if (p.priceKind !== 'sale_points' || !['draft', 'publish_ack_pending', 'publish_failed'].includes(p.status)) return fail('该版本不能发布');
  if (!(Number(p.amount) > 0)) return fail('草稿金额无效，请先编辑草稿');
  db.ttsAdmin.prices.forEach((x) => {
    if (x !== p && x.priceKind === 'sale_points' && x.operation === p.operation && x.lifecycleStatus === 'active') {
      x.lifecycleStatus = 'superseded';
    }
  });
  p.status = 'published';
  p.lifecycleStatus = 'active';
  p.publishReason = String(body.reason || '');
  return ok(clone(p), '演示：已发布，没有影响真实计费');
});

route('POST', '/admin/official-tts/prices/sync', ({ db, user, body }) => {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensure(db);
  const p = db.ttsAdmin.prices.find((x) => x.id === Number(body.id));
  if (!p) return fail('价格版本不存在');
  if (p.status === 'publish_ack_pending') p.status = 'published';
  return ok(clone(p), '演示：状态已同步');
});

function ledgerOf(db, j) {
  const acc = (db.accounts || {})[j.userId] || { balance: 0 };
  const used = (db.ttsJobs || []).filter((x) => x.userId === j.userId).reduce((n, x) => n + Number(x.charged || 0), 0);
  return {
    jobId: j.id, billId: `demo-bill-${j.id}`, userId: j.userId, state: j.state, jobStatus: j.status,
    charged: Number(Number(j.charged || 0).toFixed(4)), held: Number(Number(j.held || 0).toFixed(4)),
    userQuota: Number((Number(acc.balance || 0) + used).toFixed(4)), userUsedQuota: Number(used.toFixed(4)),
    tokenRemainQuota: Number(Number(acc.balance || 0).toFixed(4)),
  };
}

route('GET', '/admin/official-tts/jobs/:jobId/ledger', ({ db, user, params }) => {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensure(db);
  progressJobs(db);
  const j = db.ttsJobs.find((x) => String(x.id) === String(params.jobId));
  if (!j) return fail('任务不存在');
  return ok(ledgerOf(db, j));
});

route('POST', '/admin/official-tts/notes', ({ db, user, body }) => {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensure(db);
  const j = db.ttsJobs.find((x) => x.id === Number(body.jobId));
  if (!j) return fail('任务不存在');
  if (!String(body.reason || '').trim()) return fail('请填写备注理由');
  if (db.ttsAdmin.notes.some((n) => n.operationId === body.operationId)) return ok(null, '演示：重复提交，已忽略');
  db.ttsAdmin.notes.push({ jobId: j.id, operationId: body.operationId, reason: body.reason, evidence: body.evidence, by: user.username, at: new Date().toISOString() });
  return ok(null, '演示：备注已记录');
});

route('POST', '/admin/official-tts/settle', ({ db, user, body }) => {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensure(db);
  if (body.confirmed !== true) return fail('需要二次确认');
  const j = db.ttsJobs.find((x) => x.id === Number(body.jobId));
  if (!j) return fail('任务不存在');
  if (db.ttsAdmin.settlements.some((s) => s.operationId === body.operationId)) return ok(ledgerOf(db, j), '演示：重复提交，已按上次结果处理');
  const finalTotal = Number(body.finalTotal);
  if (body.finalTotal === null || body.finalTotal === undefined || Number.isNaN(finalTotal)) return fail('最终累计费用无效');
  if (finalTotal < Number(j.charged || 0)) return fail('不得降到已确认扣费以下');
  if (finalTotal === 0 && body.confirmZero !== true) return fail('零费用结算必须勾选确认');
  if (finalTotal > Number(j.charged || 0) + Number(j.held || 0)) return fail('最终累计费用超过已扣与冻结之和');
  const add = finalTotal - Number(j.charged || 0);
  const acc = (db.accounts || {})[j.userId];
  if (acc) acc.balance = Number((Number(acc.balance || 0) - add).toFixed(4));
  j.charged = finalTotal;
  j.held = 0;
  j.state = 'settled';
  db.ttsAdmin.settlements.push({ jobId: j.id, operationId: body.operationId, finalTotal, reason: body.reason, evidence: body.evidence, by: user.username, at: new Date().toISOString() });
  return ok(ledgerOf(db, j), '演示：已结算，没有改动真实账单');
});
