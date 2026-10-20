/**
 * Mock 核心：路由表、响应构造、演示数据库（持久化 + 重置）、场景开关。
 * 各业务模块在 handlers/*.js 中用 route() 注册接口，seed/*.js 提供初始演示数据。
 */
import { MOCK_STORAGE_KEYS } from './config';

/* ───────── 响应 ───────── */

/** 正常业务响应：{ code: 0, msg: 'success', data } —— 与后端 Result 包装一致 */
export function ok(data, msg = 'success') {
  return { __mock: 'json', body: { code: 0, msg, data: data === undefined ? null : data } };
}
/** 业务错误：code 非 0，走 RequestService 的 failCallback / showDanger 原逻辑 */
export function fail(msg, code = 500) {
  return { __mock: 'json', body: { code, msg } };
}
/** 原样返回响应体（用于响应结构与通用包装不同的接口） */
export function raw(body) {
  return { __mock: 'json', body };
}
/** 二进制响应（验证码图片、音频等），对应 .type('blob') 的请求 */
export function blob(b) {
  return { __mock: 'blob', body: b };
}
/** 网络层失败（status 非 200），触发 networkFail 回调 */
export function networkError(status = 503) {
  return { __mock: 'network', status };
}

/* ───────── 路由 ───────── */

const routes = [];

/**
 * 注册接口。pattern 写法与后端路径一致，参数用 :name，例如 '/agent/:agentId'。
 * 匹配时忽略 query；query 通过 req.query 读取。
 */
export function route(method, pattern, handler) {
  const keys = [];
  const re = new RegExp('^' + pattern.replace(/\/:([A-Za-z_]\w*)/g, (_, k) => { keys.push(k); return '/([^/]+)'; }) + '/?$');
  routes.push({ method: method.toUpperCase(), pattern, re, keys, handler });
}

/** 同时命中多条时取最具体的一条（字面段最多），与注册顺序无关：/agent/template 优先于 /agent/:agentId */
export function findRoute(method, path) {
  let best = null;
  for (const r of routes) {
    if (r.method !== method) continue;
    const m = r.re.exec(path);
    if (!m) continue;
    const literal = r.pattern.split('/').filter((s) => s && s[0] !== ':').length;
    if (!best || literal > best.literal) {
      const params = {};
      r.keys.forEach((k, i) => { params[k] = decodeURIComponent(m[i + 1]); });
      best = { route: r, params, literal };
    }
  }
  return best;
}

export function listRoutes() {
  return routes.map((r) => `${r.method} ${r.pattern}`);
}

/* ───────── 演示数据库 ───────── */

const seeds = [];
/** 注册某个模块的初始演示数据：fn() 返回要合并进数据库的对象 */
export function seed(fn) {
  seeds.push(fn);
}

let db = null;

function buildSeed() {
  const base = { __version: 1, __seededAt: new Date().toISOString(), seq: 1000 };
  seeds.forEach((fn) => Object.assign(base, fn()));
  return base;
}

function safeGet(key) {
  try { return window.localStorage.getItem(key); } catch (e) { return null; }
}
function safeSet(key, value) {
  try { window.localStorage.setItem(key, value); } catch (e) { /* 隐私模式等，退回仅内存 */ }
}
function safeRemove(key) {
  try { window.localStorage.removeItem(key); } catch (e) { /* ignore */ }
}

export function getDb() {
  if (db) return db;
  const stored = safeGet(MOCK_STORAGE_KEYS.db);
  if (stored) {
    try { db = JSON.parse(stored); } catch (e) { db = null; }
  }
  if (!db) {
    db = buildSeed();
    saveDb();
  }
  return db;
}

export function saveDb() {
  if (db) safeSet(MOCK_STORAGE_KEYS.db, JSON.stringify(db));
}

/** 恢复初始演示数据（不影响真实服务，因为 mock 模式下从不访问真实服务） */
export function resetDb() {
  db = buildSeed();
  saveDb();
  return db;
}

export function nextId(prefix = '') {
  const d = getDb();
  d.seq = (d.seq || 1000) + 1;
  return prefix ? `${prefix}${d.seq}` : d.seq;
}

/* ───────── 演示场景 ───────── */

export const SCENARIOS = {
  data: ['normal', 'empty', 'error'],      // 正常 / 空数据 / 服务异常
  balance: ['realtime', 'stale', 'unavailable'],  // 余额：实时 / 可能不是最新 / 暂不可用
};

export function getScenario() {
  const fallback = { data: 'normal', balance: 'realtime' };
  const stored = safeGet(MOCK_STORAGE_KEYS.scenario);
  if (!stored) return fallback;
  try { return Object.assign(fallback, JSON.parse(stored)); } catch (e) { return fallback; }
}

export function setScenario(patch) {
  const next = Object.assign(getScenario(), patch);
  safeSet(MOCK_STORAGE_KEYS.scenario, JSON.stringify(next));
  return next;
}

export function clearMockStorage() {
  safeRemove(MOCK_STORAGE_KEYS.db);
  safeRemove(MOCK_STORAGE_KEYS.scenario);
  db = null;
}

/* ───────── 常用工具 ───────── */

/** 分页：返回 { list, total }。page 从 1 开始 */
export function paginate(list, page, limit) {
  const p = Math.max(1, Number(page) || 1);
  const l = Math.max(1, Number(limit) || 10);
  return { list: list.slice((p - 1) * l, p * l), total: list.length };
}

export function nowStr(d = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function minutesAgo(min) {
  return nowStr(new Date(Date.now() - min * 60000));
}

export function includesText(value, keyword) {
  if (!keyword) return true;
  return String(value == null ? '' : value).toLowerCase().includes(String(keyword).toLowerCase());
}

/** 把 FormData / 字符串 / 对象统一转成普通对象，便于处理上传请求 */
export function bodyToObject(body) {
  if (!body) return {};
  if (typeof FormData !== 'undefined' && body instanceof FormData) {
    const o = {};
    body.forEach((v, k) => {
      if (typeof File !== 'undefined' && v instanceof File) {
        o[k] = { __file: true, name: v.name, size: v.size, type: v.type };
      } else {
        o[k] = v;
      }
    });
    return o;
  }
  if (typeof body === 'string') {
    try { return JSON.parse(body); } catch (e) { return { __text: body }; }
  }
  if (Array.isArray(body)) return body;
  return Object.assign({}, body);
}

export function clone(o) {
  return o == null ? o : JSON.parse(JSON.stringify(o));
}

/** 管理员接口：非管理员返回 403 业务错误（真实权限以后端为准，这里只是让演示行为一致） */
export function requireAdmin(user) {
  return user && user.superAdmin === 1 ? null : fail('没有权限执行此操作（需要管理员）', 403);
}
