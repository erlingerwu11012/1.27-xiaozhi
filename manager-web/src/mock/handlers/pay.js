/**
 * 余额、充值、账单（/pay/*）。
 * 不会产生任何真实支付：创建订单只生成本地演示订单，支付结果由演示流程模拟。
 * 余额来源 balanceSource 与原接口取值一致：'oneapi' | 'cache' | 'hardware_ledger' | null（演示面板可切换）。
 */
import { route, ok } from '../core';

export function quotaFor(db, user, scenario) {
  const acc = (db.accounts || {})[user.id] || { balance: 0 };
  if (scenario.balance === 'unavailable') return { balance: null, balanceRealtime: false, balanceSource: null };
  if (scenario.balance === 'stale') return { balance: acc.balance, balanceRealtime: false, balanceSource: 'cache' };
  return { balance: acc.balance, balanceRealtime: true, balanceSource: 'oneapi' };
}

route('GET', '/pay/quota/me', ({ db, user, scenario }) => ok(quotaFor(db, user, scenario)));
