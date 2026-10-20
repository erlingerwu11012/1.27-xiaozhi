/**
 * 字典（/admin/dict/*）
 * - 按类型读取字典数据（固件类型、手机区号等）：普通用户页面也会用到，不要求管理员；
 * - 字典类型 / 字典数据的分页、详情、新增、修改、删除：仅管理员。
 *   字典数据改动后会同步重建 db.dictByType，设备页、登录页读到的选项随之更新。
 */
import { route, ok, fail, requireAdmin, paginate, includesText, nowStr } from '../core';
import { ensureAdminData, syncDictByType } from '../seed/admin';

route('GET', '/admin/dict/data/type/:dictType', ({ params, db }) => ok((db.dictByType[params.dictType] || []).map((x) => ({ ...x }))));

function guard(user, db) {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensureAdminData(db);
  return null;
}
const ids = (body) => (Array.isArray(body) ? body : []).map(String);
const newId = (db) => { db.seq = (db.seq || 1000) + 1; return db.seq; };
const byId = (list, id) => list.find((x) => String(x.id) === String(id));

/* ───────── 字典类型 ───────── */

function checkType(body, db) {
  const type = String(body.dictType || '').trim();
  if (!String(body.dictName || '').trim()) return '请输入字典类型名称';
  if (!type) return '请输入字典类型编码';
  if (db.dictTypes.some((t) => t.dictType === type && String(t.id) !== String(body.id || ''))) return `字典类型编码 ${type} 已存在`;
  return '';
}

route('GET', '/admin/dict/type/page', ({ query, user, db, scenario }) => {
  const denied = guard(user, db); if (denied) return denied;
  if (scenario.data === 'empty') return ok({ list: [], total: 0 });
  const list = db.dictTypes
    .filter((t) => includesText(t.dictType, query.dictType) && includesText(t.dictName, query.dictName))
    .slice().sort((a, b) => (a.sort || 0) - (b.sort || 0))
    .map((t) => ({ ...t }));
  return ok(paginate(list, query.page, query.limit));
});

route('GET', '/admin/dict/type/:id', ({ params, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const t = byId(db.dictTypes, params.id);
  return t ? ok({ ...t }) : fail('字典类型不存在或已被删除');
});

route('POST', '/admin/dict/type/save', ({ body, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const err = checkType(body, db); if (err) return fail(err);
  const maxSort = db.dictTypes.reduce((n, t) => Math.max(n, t.sort || 0), 0);
  db.dictTypes.push({ id: newId(db), dictType: String(body.dictType).trim(), dictName: String(body.dictName).trim(), remark: body.remark || '', sort: maxSort + 1, createDate: nowStr(), updateDate: nowStr() });
  syncDictByType(db);
  return ok(null);
});

route('PUT', '/admin/dict/type/update', ({ body, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const t = byId(db.dictTypes, body.id);
  if (!t) return fail('字典类型不存在或已被删除');
  const err = checkType(body, db); if (err) return fail(err);
  Object.assign(t, { dictType: String(body.dictType).trim(), dictName: String(body.dictName).trim(), remark: body.remark == null ? t.remark : body.remark, updateDate: nowStr() });
  syncDictByType(db);
  return ok(null);
});

route('POST', '/admin/dict/type/delete', ({ body, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const list = ids(body);
  if (!list.length) return fail('请选择要删除的字典类型');
  db.dictTypes = db.dictTypes.filter((t) => !list.includes(String(t.id)));
  db.dictData = db.dictData.filter((d) => !list.includes(String(d.dictTypeId)));
  syncDictByType(db);
  return ok(null);
});

/* ───────── 字典数据 ───────── */

function checkData(body, db) {
  if (!byId(db.dictTypes, body.dictTypeId)) return '字典类型不存在，请刷新后重试';
  const value = String(body.dictValue == null ? '' : body.dictValue).trim();
  if (!String(body.dictLabel || '').trim()) return '请输入字典标签';
  if (!value) return '请输入字典值';
  if (db.dictData.some((d) => String(d.dictTypeId) === String(body.dictTypeId) && d.dictValue === value && String(d.id) !== String(body.id || ''))) {
    return `字典值 ${value} 已存在`;
  }
  return '';
}

route('GET', '/admin/dict/data/page', ({ query, user, db, scenario }) => {
  const denied = guard(user, db); if (denied) return denied;
  if (scenario.data === 'empty') return ok({ list: [], total: 0 });
  const list = db.dictData
    .filter((d) => String(d.dictTypeId) === String(query.dictTypeId) && includesText(d.dictLabel, query.dictLabel) && includesText(d.dictValue, query.dictValue))
    .slice().sort((a, b) => (a.sort || 0) - (b.sort || 0))
    .map((d) => ({ ...d }));
  return ok(paginate(list, query.page, query.limit));
});

route('GET', '/admin/dict/data/:id', ({ params, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const d = byId(db.dictData, params.id);
  return d ? ok({ ...d }) : fail('字典数据不存在或已被删除');
});

route('POST', '/admin/dict/data/save', ({ body, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const err = checkData(body, db); if (err) return fail(err);
  const t = byId(db.dictTypes, body.dictTypeId);
  db.dictData.push({ id: newId(db), dictTypeId: t.id, dictLabel: String(body.dictLabel).trim(), dictValue: String(body.dictValue).trim(), remark: body.remark || '', sort: Number(body.sort) || 0, createDate: nowStr(), updateDate: nowStr() });
  syncDictByType(db);
  return ok(null);
});

route('PUT', '/admin/dict/data/update', ({ body, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const d = byId(db.dictData, body.id);
  if (!d) return fail('字典数据不存在或已被删除');
  const err = checkData({ ...body, dictTypeId: body.dictTypeId || d.dictTypeId }, db); if (err) return fail(err);
  Object.assign(d, { dictLabel: String(body.dictLabel).trim(), dictValue: String(body.dictValue).trim(), sort: Number(body.sort) || 0, remark: body.remark == null ? d.remark : body.remark, updateDate: nowStr() });
  syncDictByType(db);
  return ok(null);
});

route('POST', '/admin/dict/data/delete', ({ body, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const list = ids(body);
  if (!list.length) return fail('请选择要删除的字典数据');
  db.dictData = db.dictData.filter((d) => !list.includes(String(d.id)));
  syncDictByType(db);
  return ok(null);
});
