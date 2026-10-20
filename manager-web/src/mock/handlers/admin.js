/**
 * 系统管理（/admin/users、/admin/params、/admin/server）。全部需要管理员身份。
 * - 用户列表来自 db.users；设备数按 db.devices 实时统计。
 * - 重置密码：只在内存里生成一个明显的演示密码返回给页面，不保存、不写入任何存储。
 * - 参数：密钥类参数（api_key / secret / token …）只保存占位值，新输入的内容不会被保存。
 * - 服务端管理：WebSocket 地址取自参数 server.websocket；“重启 / 更新配置”只返回演示结果，不连接任何服务器。
 * /admin/users/changeStatus/:status 在 handlers/user.js。
 */
import { route, ok, fail, requireAdmin, paginate, includesText, nowStr } from '../core';
import { DEMO_USERS } from '../seed/core';
import { ensureAdminData, isSecretKey, sanitizeSecret } from '../seed/admin';

const BUILTIN_IDS = [DEMO_USERS.user.id, DEMO_USERS.admin.id];
const VALUE_TYPES = ['string', 'number', 'boolean', 'array', 'json'];
const empty = () => ok({ list: [], total: 0 });

function guard(user, db) {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensureAdminData(db);
  return null;
}

/* ───────── 用户 ───────── */

function userRow(u, db) {
  return {
    userid: u.id,
    // 后端的 mobile 列取自账号（手机号注册时账号就是手机号）；演示账号没有手机号时显示账号名，见集成文档“待确认”
    mobile: u.mobile || u.username,
    deviceCount: (db.devices || []).filter((d) => d.userId === u.id).length,
    status: u.status,
    createDate: u.createDate,
  };
}

route('GET', '/admin/users', ({ query, user, db, scenario }) => {
  const denied = guard(user, db); if (denied) return denied;
  if (scenario.data === 'empty') return empty();
  const kw = query.mobile && query.mobile !== 'undefined' ? query.mobile : '';
  const list = db.users
    .filter((u) => includesText(u.mobile, kw) || includesText(u.username, kw))
    .sort((a, b) => String(b.createDate).localeCompare(String(a.createDate)))
    .map((u) => userRow(u, db));
  return ok(paginate(list, query.page, query.limit));
});

route('DELETE', '/admin/users/:id', ({ params, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const target = db.users.find((u) => String(u.id) === params.id);
  if (!target) return fail('用户不存在或已被删除');
  if (target.id === user.id) return fail('不能删除当前登录的账号');
  if (BUILTIN_IDS.includes(target.id)) return fail('内置演示账号不能删除（演示限制，可改为禁用）');
  const agentIds = (db.agents || []).filter((a) => a.userId === target.id).map((a) => a.id);
  db.users = db.users.filter((u) => u.id !== target.id);
  db.agents = (db.agents || []).filter((a) => a.userId !== target.id);
  db.devices = (db.devices || []).filter((d) => d.userId !== target.id && !agentIds.includes(d.agentId));
  Object.keys(db.sessions || {}).forEach((t) => { if (db.sessions[t].userId === target.id) delete db.sessions[t]; });
  return ok(null, '已删除（演示数据）');
});

/** 重置密码：返回本次生成的演示密码；不保存任何密码 */
route('PUT', '/admin/users/:id', ({ params, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  if (!db.users.some((u) => String(u.id) === params.id)) return fail('用户不存在或已被删除');
  const alphabet = 'abcdefghjkmnpqrstuvwxyz23456789';
  let tail = '';
  for (let i = 0; i < 6; i++) tail += alphabet[Math.floor(Math.random() * alphabet.length)];
  return ok(`demo-${tail}`, '演示密码，只在本次显示，未保存');
});

/* ───────── 参数 ───────── */

function checkParam(body, db) {
  const code = String(body.paramCode || '').trim();
  const value = body.paramValue == null ? '' : String(body.paramValue);
  const type = body.valueType || 'string';
  if (!code) return '请输入参数编码';
  if (!value.trim()) return '参数值不能为空';
  if (!VALUE_TYPES.includes(type)) return '值类型不正确';
  if (db.params.some((p) => p.paramCode === code && String(p.id) !== String(body.id || ''))) return `参数编码 ${code} 已存在`;
  if (!isSecretKey(code)) {
    if (type === 'number' && !/^-?\d+(\.\d+)?$/.test(value.trim())) return '值类型为数字时，参数值必须是数字';
    if (type === 'boolean' && !['true', 'false'].includes(value.trim())) return '值类型为布尔时，参数值只能是 true 或 false';
    if (type === 'json') { try { JSON.parse(value); } catch (e) { return '值类型为 JSON 时，参数值必须是合法的 JSON'; } }
  }
  return '';
}

route('GET', '/admin/params/page', ({ query, user, db, scenario }) => {
  const denied = guard(user, db); if (denied) return denied;
  if (scenario.data === 'empty') return empty();
  const kw = query.paramCode || '';
  const list = db.params.filter((p) => includesText(p.paramCode, kw) || includesText(p.remark, kw))
    .slice().sort((a, b) => String(a.paramCode).localeCompare(String(b.paramCode)))
    .map((p) => ({ ...p }));
  return ok(paginate(list, query.page, query.limit));
});

route('POST', '/admin/params', ({ body, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const err = checkParam(body, db); if (err) return fail(err);
  const code = String(body.paramCode).trim();
  const s = isSecretKey(code) ? sanitizeSecret(code, String(body.paramValue), '') : { value: String(body.paramValue), replaced: false };
  db.seq = (db.seq || 1000) + 1;
  db.params.push({ id: db.seq, paramCode: code, paramValue: s.value, valueType: body.valueType || 'string', remark: body.remark || '', createDate: nowStr(), updateDate: nowStr() });
  return ok(null, s.replaced ? '已保存。演示环境不保存密钥，已用占位值代替' : 'success');
});

route('PUT', '/admin/params', ({ body, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const row = db.params.find((p) => String(p.id) === String(body.id));
  if (!row) return fail('参数不存在或已被删除');
  const err = checkParam(body, db); if (err) return fail(err);
  const code = String(body.paramCode).trim();
  const s = isSecretKey(code) ? sanitizeSecret(code, String(body.paramValue), row.paramValue) : { value: String(body.paramValue), replaced: false };
  Object.assign(row, { paramCode: code, paramValue: s.value, valueType: body.valueType || row.valueType || 'string', remark: body.remark == null ? row.remark : body.remark, updateDate: nowStr() });
  return ok(null, s.replaced ? '已保存。演示环境不保存密钥，已用占位值代替' : 'success');
});

route('POST', '/admin/params/delete', ({ body, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const ids = (Array.isArray(body) ? body : []).map(String);
  if (!ids.length) return fail('请选择要删除的参数');
  db.params = db.params.filter((p) => !ids.includes(String(p.id)));
  return ok(null);
});

/* ───────── 服务端 ───────── */

function wsList(db) {
  const p = db.params.find((x) => x.paramCode === 'server.websocket');
  return p ? String(p.paramValue).split(';').map((s) => s.trim()).filter(Boolean) : [];
}

route('GET', '/admin/server/server-list', ({ user, db, scenario }) => {
  const denied = guard(user, db); if (denied) return denied;
  if (scenario.data === 'empty') return ok([]);
  return ok(wsList(db));
});

route('POST', '/admin/server/emit-action', ({ body, user, db }) => {
  const denied = guard(user, db); if (denied) return denied;
  const labels = { restart: '重启', update_config: '更新配置' };
  if (!labels[body.action]) return fail('不支持的操作');
  if (!wsList(db).includes(body.targetWs)) return fail('目标服务端不在列表中，请刷新后重试');
  return ok(true, `演示结果：已模拟向 ${body.targetWs} 发送“${labels[body.action]}”指令，没有连接真实服务器`);
});
