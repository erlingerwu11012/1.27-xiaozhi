/**
 * 余额、充值、账单（/pay/*）。
 * 不会产生任何真实支付：创建订单只生成本地演示订单，付款结果由页面里的“演示付款”确认框模拟（simulatePayment）。
 * 余额来源 balanceSource 与原接口取值一致：'oneapi' | 'cache' | 'hardware_ledger' | null（演示面板可切换）。
 *
 * 订单状态流转（演示）：pending →（演示付款成功）paid →（约 2.5 秒后查询时）delivered，并把点数加到演示余额；
 * pending →（演示付款失败）failed；pending 超过 15 分钟未付款 → closed。
 */
import { route, ok, fail, getDb, saveDb, paginate, clone } from '../core';
import { buildBillingSeed } from '../seed/billing';

const DELIVER_AFTER_MS = 2500;
const CLOSE_AFTER_MS = 15 * 60000;

/** 旧的本机演示数据里没有账单集合时补上（不覆盖已有数据） */
function ensure(db) {
  if (!db.payPackages || !db.payOrders || !db.payCalls || !db.memoryBills) {
    const s = buildBillingSeed();
    Object.keys(s).forEach((k) => { if (!db[k]) db[k] = s[k]; });
    saveDb();
  }
  if (!db.accounts) db.accounts = {};
  return db;
}

function account(db, userId) {
  if (!db.accounts[userId]) db.accounts[userId] = { balance: 0 };
  return db.accounts[userId];
}

/** 按时间推进订单状态：已付款的到账、长时间未付款的关闭 */
function progressOrders(db) {
  const now = Date.now();
  let changed = false;
  (db.payOrders || []).forEach((o) => {
    if (o.status === 'paid' && o.paidAt && now - o.paidAt >= DELIVER_AFTER_MS) {
      o.status = 'delivered';
      o.deliveredAt = now;
      const acc = account(db, o.userId);
      acc.balance = Number((Number(acc.balance || 0) + Number(o.quotaPoints || 0)).toFixed(4));
      changed = true;
    } else if (o.status === 'pending' && now - new Date(o.createdAt).getTime() >= CLOSE_AFTER_MS) {
      o.status = 'closed';
      changed = true;
    }
  });
  if (changed) saveDb();
}

export function quotaFor(db, user, scenario) {
  const acc = (db.accounts || {})[user.id] || { balance: 0 };
  if (scenario.balance === 'unavailable') return { balance: null, balanceRealtime: false, balanceSource: null };
  if (scenario.balance === 'stale') return { balance: acc.balance, balanceRealtime: false, balanceSource: 'cache' };
  return { balance: acc.balance, balanceRealtime: true, balanceSource: 'oneapi' };
}

/** 订单对外字段（BillingOrders 表格 / BillingResult 读取的字段） */
function orderRow(o) {
  return {
    outTradeNo: o.outTradeNo, packageName: o.packageName, amountCents: o.amountCents, quotaPoints: o.quotaPoints,
    channel: o.channel, status: o.status, createdAt: o.createdAt,
  };
}

/**
 * 演示付款：只在 mock 构建里由 BillingPackages 的“演示付款”确认框调用，不是接口。
 * result: 'success' → paid（稍后查询时到账）；'fail' → failed。
 */
export function simulatePayment(outTradeNo, result) {
  const db = ensure(getDb());
  const o = (db.payOrders || []).find((x) => x.outTradeNo === outTradeNo);
  if (!o || o.status !== 'pending') return false;
  if (result === 'success') {
    o.status = 'paid';
    o.paidAt = Date.now();
  } else {
    o.status = 'failed';
  }
  saveDb();
  return true;
}

const pad = (n) => String(n).padStart(2, '0');
const dayKey = (ms) => { const d = new Date(ms); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
const round4 = (n) => Number(Number(n).toFixed(4));

route('GET', '/pay/quota/me', ({ db, user, scenario }) => {
  ensure(db);
  progressOrders(db);
  return ok(quotaFor(db, user, scenario));
});

route('GET', '/pay/packages', ({ db, scenario }) => {
  ensure(db);
  if (scenario.data === 'empty') return ok([]);
  return ok(clone(db.payPackages).sort((a, b) => (a.sort || 0) - (b.sort || 0)));
});

route('POST', '/pay/order/create', ({ db, user, body }) => {
  ensure(db);
  const pkg = db.payPackages.find((p) => p.id === body.packageId);
  if (!pkg) return fail('套餐不存在或已下架，请刷新后重新选择');
  if (body.channel !== 'alipay') return fail('暂不支持该支付渠道');
  const d = new Date();
  const no = `DEMO${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}${Math.floor(Math.random() * 90 + 10)}`;
  const o = {
    outTradeNo: no, userId: user.id, packageId: pkg.id, packageName: pkg.name, amountCents: pkg.amountCents,
    quotaPoints: pkg.quotaPoints, channel: 'alipay', status: 'pending', createdAt: d.toISOString(), paidAt: null, deliveredAt: null,
  };
  db.payOrders.unshift(o);
  // 真实接口返回支付宝表单 payForm；演示模式不生成任何会跳转到外部的表单
  return ok({ ...orderRow(o), payForm: '' }, '演示订单已创建（不会发起真实支付）');
});

route('GET', '/pay/order/query/:orderNo', ({ db, user, params }) => {
  ensure(db);
  progressOrders(db);
  const o = db.payOrders.find((x) => x.outTradeNo === params.orderNo && (x.userId === user.id || user.superAdmin === 1));
  if (!o) return fail('未找到该订单');
  return ok(orderRow(o));
});

route('GET', '/pay/orders', ({ db, user, query, scenario }) => {
  ensure(db);
  progressOrders(db);
  if (scenario.data === 'empty') return ok({ list: [], total: 0 });
  const mine = db.payOrders.filter((o) => o.userId === user.id)
    .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt)).map(orderRow);
  return ok(paginate(mine, query.page, query.limit));
});

route('GET', '/pay/billing/summary', ({ db, user, query, scenario }) => {
  ensure(db);
  progressOrders(db);
  const days = Number(query.days) === 30 ? 30 : 7;
  const empty = scenario.data === 'empty';
  const now = Date.now();
  const daily = [];
  const byDay = {};
  for (let i = days - 1; i >= 0; i--) {
    const key = dayKey(now - i * 86400000);
    const row = { date: key, rechargeAmountCents: 0, rechargePoints: 0, usagePoints: 0, netChangePoints: 0 };
    byDay[key] = row;
    daily.push(row);
  }
  if (!empty) {
    db.payCalls.filter((c) => c.userId === user.id).forEach((c) => {
      const row = byDay[dayKey(c.createdAt * 1000)];
      if (row) row.usagePoints += Number(c.points) || 0;
    });
    db.payOrders.filter((o) => o.userId === user.id && o.status === 'delivered').forEach((o) => {
      const row = byDay[dayKey(o.deliveredAt || new Date(o.createdAt).getTime())];
      if (row) { row.rechargeAmountCents += o.amountCents; row.rechargePoints += o.quotaPoints; }
    });
  }
  daily.forEach((r) => {
    r.usagePoints = round4(r.usagePoints);
    r.netChangePoints = round4(r.rechargePoints - r.usagePoints);
  });
  const q = quotaFor(db, user, scenario);
  const unavailable = scenario.balance === 'unavailable';
  return ok({
    balancePoints: q.balance,
    balanceSource: q.balanceSource,
    balanceRealtime: q.balanceRealtime,
    consumptionAvailable: !unavailable,
    consumptionUnavailableReason: unavailable ? 'logs_unreadable' : null,
    daily,
  });
});

route('GET', '/pay/billing/calls', ({ db, user, query, scenario }) => {
  ensure(db);
  if (scenario.data === 'empty') return ok({ available: true, list: [], total: 0 });
  const mine = db.payCalls.filter((c) => c.userId === user.id);
  const { list, total } = paginate(mine, query.page, query.limit || 20);
  return ok({ available: true, list: clone(list), total });
});

route('GET', '/pay/memory-bills', ({ db, user, query, scenario }) => {
  ensure(db);
  if (scenario.data === 'empty') return ok({ available: true, list: [], total: 0 });
  const mine = db.memoryBills.filter((m) => m.userId === user.id)
    .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
  const { list, total } = paginate(mine, query.page, query.limit || 10);
  return ok({ available: true, list: clone(list), total });
});
