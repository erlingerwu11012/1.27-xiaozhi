/**
 * 习惯管理：/habits*。回调拿到的是响应体本身（res.data）：
 * - GET /habits?enabledOnly= → res.data 为数组，行字段 id / description / hour / minute / advanceMinutes /
 *   source（manual|auto）/ syncState / syncError / enabled / createdAt / deviceId / recipientPersonId；
 * - GET /habits/options → res.data.devices[{ deviceId, deviceName, alias }]、res.data.people[{ user_id, display_name }]。
 *
 * 页面只对管理员开放（路由守卫），接口本身按当前账号的设备划分（是否需要管理员权限待确认）。
 * 演示规则：新建 / 修改 / 删除后状态为“待同步”，在之后的列表刷新（页面每 15 秒一次）中变为“已同步”。
 * 不会向任何设备下发提醒。
 */
import { route, ok, fail, nowStr, nextId } from '../core';
import { buildHabits } from '../seed/knowledge';

function ensure(db) {
  if (!db.habits || !db.habitPeople) Object.assign(db, buildHabits());
  return db;
}

const ownDevices = (db, user) => (db.devices || []).filter((d) => d.userId === user.id);
const people = (db, user) => (db.habitPeople && db.habitPeople[user.id]) || [];

function publicHabit(h) {
  return {
    id: h.id, description: h.description, hour: h.hour, minute: h.minute, advanceMinutes: h.advanceMinutes,
    source: h.source, syncState: h.syncState, syncError: h.syncError || '', enabled: h.enabled,
    createdAt: h.createdAt, updatedAt: h.updatedAt || h.createdAt, deviceId: h.deviceId || '', recipientPersonId: h.recipientPersonId || '',
  };
}

/** 列表刷新时推进“待同步” */
function advanceSync(list) {
  list.forEach((h) => {
    if (h.syncState !== 'pending' || h._syncPolls == null) return;
    h._syncPolls -= 1;
    if (h._syncPolls <= 0) {
      delete h._syncPolls;
      h.syncState = 'synced';
      h.syncError = '';
    }
  });
}

function validate(db, user, body) {
  const description = String(body.description || '').trim();
  if (!description) return '请输入习惯名称';
  if (description.length > 32) return '习惯名称不能超过 32 个字符';
  const hour = Number(body.hour);
  const minute = Number(body.minute);
  if (!Number.isInteger(hour) || hour < 0 || hour > 23 || !Number.isInteger(minute) || minute < 0 || minute > 59) return '请选择触发时间';
  const adv = Number(body.advanceMinutes);
  if (!Number.isInteger(adv) || adv < 0 || adv > 30) return '提前提醒分钟数需在 0 到 30 之间';
  if (!body.deviceId || !ownDevices(db, user).some((d) => d.id === body.deviceId)) return '请选择本账号的提醒设备';
  const rid = body.recipientPersonId;
  if (!rid || (rid !== 'all' && !people(db, user).some((p) => p.user_id === rid))) return '请选择接收人';
  return '';
}

route('GET', '/habits/options', ({ db, user }) => {
  ensure(db);
  const agents = db.agents || [];
  return ok({
    devices: ownDevices(db, user).map((d) => {
      const a = agents.find((x) => x.id === d.agentId);
      return { deviceId: d.id, deviceName: d.alias || (a && a.agentName) || '', alias: d.alias || '' };
    }),
    people: people(db, user).map((p) => ({ ...p })),
  });
});

route('GET', '/habits', ({ query, db, user, scenario }) => {
  ensure(db);
  if (scenario.data === 'empty') return ok([]);
  const enabledOnly = String(query.enabledOnly) !== 'false';
  const mine = db.habits.filter((h) => h.userId === user.id);
  advanceSync(mine);
  return ok(mine.filter((h) => !enabledOnly || h.enabled === 1)
    .sort((a, b) => (b.enabled - a.enabled) || (a.hour * 60 + a.minute) - (b.hour * 60 + b.minute))
    .map(publicHabit));
});

route('POST', '/habits', ({ body, db, user }) => {
  ensure(db);
  const err = validate(db, user, body);
  if (err) return fail(err);
  const h = {
    id: nextId(), userId: user.id, description: String(body.description).trim(), hour: Number(body.hour), minute: Number(body.minute),
    advanceMinutes: Number(body.advanceMinutes), deviceId: body.deviceId, recipientPersonId: body.recipientPersonId,
    source: 'manual', enabled: 1, syncState: 'pending', syncError: '', _syncPolls: 2, createdAt: nowStr(),
  };
  db.habits.push(h);
  return ok(publicHabit(h), '已保存，等待设备同步（演示）');
});

route('PUT', '/habits/:id', ({ params, body, db, user }) => {
  ensure(db);
  const h = db.habits.find((x) => x.id === Number(params.id) && x.userId === user.id);
  if (!h) return fail('习惯不存在或无权操作');
  if (h.enabled !== 1) return fail('已删除的习惯不能编辑');
  const err = validate(db, user, body);
  if (err) return fail(err);
  Object.assign(h, {
    description: String(body.description).trim(), hour: Number(body.hour), minute: Number(body.minute),
    advanceMinutes: Number(body.advanceMinutes), deviceId: body.deviceId, recipientPersonId: body.recipientPersonId,
    syncState: 'pending', syncError: '', _syncPolls: 2, updatedAt: nowStr(),
  });
  return ok(publicHabit(h), '已保存，等待设备同步（演示）');
});

/** 软删除：enabled=0，待设备确认后显示“已停止提醒” */
route('DELETE', '/habits/:id', ({ params, db, user }) => {
  ensure(db);
  const h = db.habits.find((x) => x.id === Number(params.id) && x.userId === user.id);
  if (!h) return fail('习惯不存在或无权操作');
  if (h.enabled !== 1) return fail('这条习惯已删除');
  Object.assign(h, { enabled: 0, syncState: h.deviceId ? 'pending' : 'synced', syncError: '', _syncPolls: 2, updatedAt: nowStr() });
  return ok(null);
});
