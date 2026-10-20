/**
 * Mock 适配器：签名与 fly.request(url, data, options) 相同，返回 Promise。
 * RequestService 在 mock 模式下用它代替 flyio，因此 API 模块、URL 拼接、请求字段与回调处理都保持原样。
 *
 * - 不发出任何网络请求（没有 fetch / XHR / WebSocket）。
 * - 响应模拟 flyio：resolve({ status: 200, data })；网络失败时 reject({ status })，走原 networkFail 分支。
 * - 未覆盖的接口返回业务错误并在控制台警告，不会悄悄“成功”。
 */
import { findRoute, getDb, saveDb, getScenario, fail, bodyToObject } from './core';
import './handlers';

const API_BASE = process.env.VUE_APP_API_BASE_URL || '';
const PY_BASE = process.env.VUE_APP_PYTHON_API_URL || '';

/** 无需登录即可调用的接口（与后端白名单的实际情况可能不同，见集成文档） */
const PUBLIC_PATHS = [
  '/user/login', '/user/captcha', '/user/pub-config', '/user/register',
  '/user/smsVerification', '/user/retrieve-password',
];
/** “服务异常”演示场景下仍正常返回的接口，保证还能登录和看到外壳 */
const ALWAYS_OK_PATHS = PUBLIC_PATHS.concat(['/user/info', '/pay/quota/me']);

function stripBase(url) {
  let u = String(url || '');
  u = u.replace(/^https?:\/\/[^/]+/i, '');
  for (const base of [API_BASE, PY_BASE.replace(/^https?:\/\/[^/]+/i, '')]) {
    if (base && base !== '/' && u.indexOf(base) === 0) {
      u = u.slice(base.length);
      break;
    }
  }
  const qi = u.indexOf('?');
  const path = (qi >= 0 ? u.slice(0, qi) : u) || '/';
  const query = {};
  if (qi >= 0) {
    new URLSearchParams(u.slice(qi + 1)).forEach((v, k) => { query[k] = v; });
  }
  return { path: path.replace(/\/{2,}/g, '/'), query };
}

function currentUser(headers, db) {
  const auth = (headers && (headers.Authorization || headers.authorization)) || '';
  const token = auth.replace(/^Bearer\s+/i, '');
  const session = db.sessions && db.sessions[token];
  if (!session) return null;
  return (db.users || []).find((u) => u.id === session.userId) || null;
}

function delay() {
  return new Promise((r) => setTimeout(r, 120 + Math.random() * 220));
}

export function mockRequest(url, data, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const headers = options.headers || {};
  const { path, query } = stripBase(url);
  const body = bodyToObject(data);
  if (method === 'GET' && data && typeof data === 'object' && !(data instanceof FormData)) {
    Object.assign(query, data);
  }

  return delay().then(() => {
    const db = getDb();
    const scenario = getScenario();
    const isPublic = PUBLIC_PATHS.includes(path);
    const user = currentUser(headers, db);

    let result;
    if (!isPublic && !user) {
      result = { __mock: 'json', body: { code: 401, msg: '登录已过期，请重新登录（演示）' } };
    } else if (scenario.data === 'error' && !ALWAYS_OK_PATHS.includes(path)) {
      result = fail('服务暂时不可用，请稍后重试（演示场景：服务异常）');
    } else {
      const hit = findRoute(method, path);
      if (!hit) {
        // eslint-disable-next-line no-console
        console.warn(`[mock] 未覆盖的接口：${method} ${path}`);
        result = fail(`演示模式尚未模拟该接口：${method} ${path}`);
      } else {
        try {
          result = hit.route.handler({ method, path, params: hit.params, query, body, headers, user, db, scenario, responseType: options.responseType });
        } catch (e) {
          // eslint-disable-next-line no-console
          console.error('[mock] 处理接口出错', method, path, e);
          result = fail(`演示数据处理出错：${e.message}`);
        }
        if (method !== 'GET') saveDb();
      }
    }

    if (result && result.__mock === 'network') {
      return Promise.reject({ status: result.status, data: null, mock: true });
    }
    const resData = result && result.__mock ? result.body : result;
    return { status: 200, data: resData, headers: {}, mock: true };
  });
}

export { isMockMode, DATA_MODE, MOCK_LABEL } from './config';
