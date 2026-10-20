/**
 * 记忆管理（管理员）：/admin/memory*。
 * API 模块用 VUE_APP_PYTHON_API_URL 作前缀（本地为空），适配器会去掉前缀；回调拿到的是响应体本身（res.data），
 * MemoryManagement 读 res.code、res.data.list、res.data.total。
 *
 * 记忆内容全部以“（演示）”开头，不含真实个人信息。device_id 引用 seed/core.js 的演示设备。
 */
import { route, ok, fail, paginate, requireAdmin } from '../core';
import { buildMemory } from '../seed/knowledge';

function ensure(db) {
  if (!db.memories) Object.assign(db, buildMemory());
  return db;
}

// 设备 id 按完整匹配筛选（与“按设备 ID 筛选”的用法一致；后端是否支持模糊匹配待确认）
const sameDevice = (a, b) => String(a || '').trim().toLowerCase() === String(b || '').trim().toLowerCase();

route('GET', '/admin/memory', ({ query, db, user, scenario }) => {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensure(db);
  if (scenario.data === 'empty') return ok({ list: [], total: 0, page: 1, limit: Number(query.limit) || 20 });
  const list = db.memories
    .filter((m) => !query.device_id || sameDevice(m.device_id, query.device_id))
    .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)) || b.id - a.id)
    .map((m) => ({ id: m.id, device_id: m.device_id, category: m.category, fact: m.fact, created_at: m.created_at, updated_at: m.updated_at }));
  const p = paginate(list, query.page, query.limit || 20);
  return ok({ list: p.list, total: p.total, page: Number(query.page) || 1, limit: Number(query.limit) || 20 });
});

route('DELETE', '/admin/memory/device/:deviceId', ({ params, db, user }) => {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensure(db);
  if (!String(params.deviceId || '').trim()) return fail('请先按设备 ID 筛选');
  const before = db.memories.length;
  db.memories = db.memories.filter((m) => !sameDevice(m.device_id, params.deviceId));
  return ok({ deleted: before - db.memories.length });
});

route('DELETE', '/admin/memory/:id', ({ params, db, user }) => {
  const denied = requireAdmin(user);
  if (denied) return denied;
  ensure(db);
  const id = Number(params.id);
  if (!db.memories.some((m) => m.id === id)) return fail('这条记忆不存在或已删除');
  db.memories = db.memories.filter((m) => m.id !== id);
  return ok(null);
});
