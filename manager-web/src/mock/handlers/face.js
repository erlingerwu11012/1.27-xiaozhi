/**
 * 人脸（/face/*）：人脸资料与设备采集草稿。
 *
 * 调用方：views/UnifiedUserManagement.vue（以及已重定向的旧版 FaceManagement.vue），face 模块回调 res.data：
 * - GET  /face/profiles?include_draft=          → data.profiles: [{ user_id, display_name, status: draft|active, face_count, created_at }]
 * - POST /face/profiles { display_name }        → data: 新资料（页面读 user_id）
 * - POST /face/profiles/:id/faces (FormData image) → 照片数 +1（演示：文件不离开本机）
 * - POST /face/profiles/:id/activate            → status = active（需至少 1 张照片）
 * - DELETE /face/profiles/:id
 * - GET  /face/enrollment/sessions              → data.sessions: [{ session_id, status: collecting|draft_ready|expired, accepted_count, has_preview, created_at }]
 * - GET  /face/enrollment/sessions/:id/preview  → 图片 Blob（演示占位图）
 * - POST /face/enrollment/sessions/:id/confirm { display_name } → data: 新的已启用资料（页面读 user_id）
 * - DELETE /face/enrollment/sessions/:id
 * 设备采集草稿是演示数据：不会有设备真的拍照，也不会生成新的采集草稿。
 */
import { route, ok, fail, blob, nextId, nowStr } from '../core';
import { ensureIdentity } from '../seed/identity';
import { placeholderImage } from '../media';

const own = (db, user) => ensureIdentity(db).faceProfiles.filter((f) => f.ownerId === user.id);
const findProfile = (db, user, id) => own(db, user).find((f) => f.user_id === id);
const ownSessions = (db, user) => ensureIdentity(db).faceEnrollments.filter((s) => s.ownerId === user.id);

function profileRow(f) {
  return { user_id: f.user_id, display_name: f.display_name, status: f.status, face_count: f.face_count || 0, created_at: f.created_at };
}
function sessionRow(s) {
  return { session_id: s.session_id, device_id: s.device_id, status: s.status, accepted_count: s.accepted_count || 0, has_preview: !!s.has_preview, created_at: s.created_at };
}
function cleanName(v) {
  return String(v == null ? '' : v).trim();
}

route('GET', '/face/profiles', ({ db, user, query, scenario }) => {
  if (scenario.data === 'empty') return ok({ profiles: [] });
  const withDraft = String(query.include_draft) !== 'false';
  return ok({ profiles: own(db, user).filter((f) => withDraft || f.status === 'active').map(profileRow) });
});

route('POST', '/face/profiles', ({ db, user, body }) => {
  const name = cleanName(body.display_name);
  if (!name) return fail('请输入姓名');
  if (name.length > 64) return fail('姓名不能超过 64 个字');
  const f = { user_id: `demo-face-${nextId()}`, ownerId: user.id, display_name: name, status: 'draft', face_count: 0, created_at: nowStr() };
  db.faceProfiles.push(f);
  return ok(profileRow(f));
});

route('POST', '/face/profiles/:id/faces', ({ db, user, params, body }) => {
  const f = findProfile(db, user, params.id);
  if (!f) return fail('人脸资料不存在');
  if (f.status === 'active') return fail('资料启用后照片不可修改');
  const img = body.image;
  if (!img || !img.__file) return fail('请选择照片');
  if (!/^image\/(jpeg|png)$/.test(img.type || '')) return fail('只支持 JPG、PNG 照片');
  if (img.size > 10 * 1024 * 1024) return fail('照片不能超过 10 MB');
  f.face_count = (f.face_count || 0) + 1;
  return ok({ face_count: f.face_count }, '照片已接收（演示：文件没有离开本机）');
});

route('POST', '/face/profiles/:id/activate', ({ db, user, params }) => {
  const f = findProfile(db, user, params.id);
  if (!f) return fail('人脸资料不存在');
  if (!f.face_count) return fail('请先上传至少一张照片');
  f.status = 'active';
  return ok(profileRow(f));
});

route('DELETE', '/face/profiles/:id', ({ db, user, params }) => {
  const f = findProfile(db, user, params.id);
  if (!f) return fail('人脸资料不存在');
  db.faceProfiles = db.faceProfiles.filter((x) => x !== f);
  (db.identities || []).forEach((p) => { p.faceProfileIds = (p.faceProfileIds || []).filter((id) => id !== f.user_id); });
  return ok(null);
});

route('GET', '/face/enrollment/sessions', ({ db, user, scenario }) => {
  if (scenario.data === 'empty') return ok({ sessions: [] });
  return ok({ sessions: ownSessions(db, user).map(sessionRow) });
});

route('GET', '/face/enrollment/sessions/:id/preview', ({ db, user, params }) => {
  const s = ownSessions(db, user).find((x) => x.session_id === params.id);
  if (!s || !s.has_preview) return fail('预览不存在');
  const dataUrl = placeholderImage('设备采集预览', 160, 160);
  const svg = decodeURIComponent(dataUrl.slice(dataUrl.indexOf(',') + 1));
  return blob(new Blob([svg], { type: 'image/svg+xml' }));
});

route('POST', '/face/enrollment/sessions/:id/confirm', ({ db, user, params, body }) => {
  const s = ownSessions(db, user).find((x) => x.session_id === params.id);
  if (!s) return fail('采集草稿不存在或已被处理');
  if (s.status !== 'draft_ready') return fail('照片尚未采集合格（至少 3 张），请稍候');
  const name = cleanName(body.display_name);
  if (!name) return fail('请输入姓名');
  const f = { user_id: `demo-face-${nextId()}`, ownerId: user.id, display_name: name, status: 'active', face_count: s.accepted_count || 0, created_at: nowStr() };
  db.faceProfiles.push(f);
  db.faceEnrollments = db.faceEnrollments.filter((x) => x !== s);
  return ok(profileRow(f));
});

route('DELETE', '/face/enrollment/sessions/:id', ({ db, user, params }) => {
  const s = ownSessions(db, user).find((x) => x.session_id === params.id);
  if (!s) return fail('采集草稿不存在或已被处理');
  db.faceEnrollments = db.faceEnrollments.filter((x) => x !== s);
  return ok(null);
});
