/**
 * 演示模式控制（只在 mock 模式下由“演示模式”面板调用）。
 * 切换演示身份 = 在本地演示数据里为另一个演示账号建立会话，之后应用仍通过 /user/info 读取 superAdmin，
 * 与正式的权限判断走同一条代码路径；它不是授权机制，real 模式下不存在。
 */
import { getDb, saveDb, resetDb, getScenario, setScenario, clearMockStorage } from './core';
import './handlers';
import { DEMO_USERS } from './seed/core';

export { getScenario, setScenario };

export function demoAccounts() {
  return DEMO_USERS;
}

/** 返回可写入 store.setToken 的 token 字符串（与登录接口返回的 data 结构一致） */
export function signInAs(role) {
  const db = getDb();
  const account = DEMO_USERS[role];
  const user = db.users.find((u) => u.id === account.id);
  if (!user) return null;
  user.status = 1;
  const token = `mock-${user.username}-${Math.random().toString(36).slice(2, 10)}`;
  db.sessions[token] = { userId: user.id, createdAt: Date.now() };
  saveDb();
  return JSON.stringify({ token, expire: 43200, clientHash: '' });
}

export function resetDemoData() {
  clearMockStorage();
  resetDb();
}
