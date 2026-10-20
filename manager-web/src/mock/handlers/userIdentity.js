/**
 * 人员身份（/user-identities/*）：一位成员 = 一个身份，人脸资料与声纹都绑定到成员上。
 *
 * 调用方：views/UnifiedUserManagement.vue，经 userIdentity 模块的 request() 回调 res.data，
 * 页面只读 code 与 data（成员数组 / 声纹数组 / 新成员对象）。
 * - 成员：{ userId, displayName, faceProfileIds: [], voiceprintIds: [], createdAt }
 * - 声纹：与 /agent/voice-print 同一份演示数据（handlers/agent-extra.js 的 voicePrints），字段 id / sourceName / introduce / audioId / agentId / createDate
 * 通过 POST /agent/voice-print 带 userId 新建的声纹，读取成员列表时自动归到该成员（原页面依赖的行为，见集成文档“待确认”）。
 */
import { route, ok, fail, nextId, nowStr } from '../core';
import { ownVoicePrints, voicePrintRow } from './agent-extra';
import { ensureIdentity } from '../seed/identity';

const MAX_NAME = 64;

export function ownIdentities(db, user) {
  ensureIdentity(db);
  return db.identities.filter((p) => p.ownerId === user.id);
}
function findIdentity(db, user, userId) {
  return ownIdentities(db, user).find((p) => p.userId === userId);
}
/** 某个人脸 / 声纹当前归属的成员（同一资料只能属于一位成员） */
function ownerOf(db, user, field, id) {
  return ownIdentities(db, user).find((p) => (p[field] || []).includes(id));
}

function checkName(name) {
  const v = String(name == null ? '' : name).trim();
  if (!v) return { err: '请填写昵称' };
  if (v.length > MAX_NAME) return { err: `昵称不能超过 ${MAX_NAME} 个字` };
  return { value: v };
}

/** 把带 userId 的声纹归到对应成员；已删除的声纹从绑定里去掉 */
function syncVoiceBindings(db, user) {
  const voices = ownVoicePrints(db, user);
  const ids = new Set(voices.map((v) => v.id));
  ownIdentities(db, user).forEach((p) => {
    p.voiceprintIds = (p.voiceprintIds || []).filter((id) => ids.has(id));
  });
  voices.forEach((v) => {
    if (!v.userId) return;
    const p = findIdentity(db, user, v.userId);
    if (p && !p.voiceprintIds.includes(v.id) && !ownerOf(db, user, 'voiceprintIds', v.id)) p.voiceprintIds.push(v.id);
  });
}

function row(p) {
  return { userId: p.userId, displayName: p.displayName, faceProfileIds: (p.faceProfileIds || []).slice(), voiceprintIds: (p.voiceprintIds || []).slice(), createdAt: p.createdAt };
}

route('GET', '/user-identities/users', ({ db, user, scenario }) => {
  if (scenario.data === 'empty') return ok([]);
  syncVoiceBindings(db, user);
  const faces = new Set((db.faceProfiles || []).filter((f) => f.ownerId === user.id).map((f) => f.user_id));
  return ok(ownIdentities(db, user).map((p) => {
    const r = row(p);
    r.faceProfileIds = r.faceProfileIds.filter((id) => faces.has(id));
    return r;
  }));
});

route('GET', '/user-identities/voiceprints', ({ db, user, scenario }) => {
  if (scenario.data === 'empty') return ok([]);
  return ok(ownVoicePrints(db, user).map(voicePrintRow));
});

route('POST', '/user-identities/users', ({ db, user, body }) => {
  const { err, value } = checkName(body.displayName);
  if (err) return fail(err);
  if (ownIdentities(db, user).some((p) => p.displayName === value)) return fail('已经有同名成员，请换一个昵称');
  const p = { userId: `demo-p-${nextId()}`, ownerId: user.id, displayName: value, faceProfileIds: [], voiceprintIds: [], createdAt: nowStr() };
  db.identities.push(p);
  return ok(row(p));
});

route('PUT', '/user-identities/users/:userId/display-name', ({ db, user, params, body }) => {
  const p = findIdentity(db, user, params.userId);
  if (!p) return fail('成员不存在或已被删除');
  const { err, value } = checkName(body.displayName);
  if (err) return fail(err);
  if (ownIdentities(db, user).some((x) => x !== p && x.displayName === value)) return fail('已经有同名成员，请换一个昵称');
  p.displayName = value;
  return ok(null);
});

/** 删除成员：连同其人脸资料与声纹一起删除（原页面确认文案“删除该成员的人脸、声纹及相关记录”） */
route('DELETE', '/user-identities/users/:userId', ({ db, user, params }) => {
  const p = findIdentity(db, user, params.userId);
  if (!p) return fail('成员不存在或已被删除');
  const faceIds = new Set(p.faceProfileIds || []);
  const voiceIds = new Set(p.voiceprintIds || []);
  db.faceProfiles = (db.faceProfiles || []).filter((f) => !(f.ownerId === user.id && faceIds.has(f.user_id)));
  if (db.voicePrints) db.voicePrints = db.voicePrints.filter((v) => !voiceIds.has(v.id) && v.userId !== p.userId);
  db.identities = db.identities.filter((x) => x !== p);
  return ok(null);
});

route('POST', '/user-identities/users/:userId/faces/:faceId', ({ db, user, params }) => {
  const p = findIdentity(db, user, params.userId);
  if (!p) return fail('成员不存在或已被删除');
  const f = (db.faceProfiles || []).find((x) => x.user_id === params.faceId && x.ownerId === user.id);
  if (!f) return fail('人脸资料不存在');
  const owner = ownerOf(db, user, 'faceProfileIds', f.user_id);
  if (owner && owner !== p) return fail(`这份人脸资料已经绑定给「${owner.displayName}」`);
  if (!p.faceProfileIds.includes(f.user_id)) p.faceProfileIds.push(f.user_id);
  return ok(null);
});

route('DELETE', '/user-identities/users/:userId/faces/:faceId', ({ db, user, params }) => {
  const p = findIdentity(db, user, params.userId);
  if (!p) return fail('成员不存在或已被删除');
  p.faceProfileIds = (p.faceProfileIds || []).filter((id) => id !== params.faceId);
  return ok(null);
});

route('POST', '/user-identities/users/:userId/voiceprints/:voiceId', ({ db, user, params }) => {
  const p = findIdentity(db, user, params.userId);
  if (!p) return fail('成员不存在或已被删除');
  const v = ownVoicePrints(db, user).find((x) => x.id === params.voiceId);
  if (!v) return fail('声纹不存在');
  const owner = ownerOf(db, user, 'voiceprintIds', v.id);
  if (owner && owner !== p) return fail(`这段声纹已经绑定给「${owner.displayName}」`);
  if (!p.voiceprintIds.includes(v.id)) p.voiceprintIds.push(v.id);
  v.userId = p.userId;
  return ok(null);
});

route('DELETE', '/user-identities/users/:userId/voiceprints/:voiceId', ({ db, user, params }) => {
  const p = findIdentity(db, user, params.userId);
  if (!p) return fail('成员不存在或已被删除');
  p.voiceprintIds = (p.voiceprintIds || []).filter((id) => id !== params.voiceId);
  const v = ownVoicePrints(db, user).find((x) => x.id === params.voiceId);
  if (v && v.userId === p.userId) v.userId = null;
  return ok(null);
});
