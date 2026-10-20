/**
 * 账单与充值的演示数据：充值套餐、订单、调用明细、官方服务（记忆）费用。
 * 套餐名称与价格全部是演示值（“演示套餐 A/B/C”），不代表真实售价；充值是一次性购买点数，不是订阅。
 * 时间相对“生成演示数据的时刻”计算；重置演示数据时会重新生成。
 */
import { seed } from '../core';
import { DEMO_USERS } from './core';

const DAY = 86400000;
const iso = (ms) => new Date(ms).toISOString();

/** 固定种子的伪随机数，保证每次重置得到同样的演示数据 */
function rng(seedNum) {
  let s = seedNum >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

export const DEMO_PACKAGES = [
  { id: 'demo-pkg-a', name: '演示套餐 A', amountCents: 100, quotaPoints: 100, description: '演示数据：用于体验充值流程', sort: 1 },
  { id: 'demo-pkg-b', name: '演示套餐 B', amountCents: 500, quotaPoints: 520, description: '演示数据：价格与点数仅作示例', sort: 2 },
  { id: 'demo-pkg-c', name: '演示套餐 C', amountCents: 2000, quotaPoints: 2150, description: '演示数据：不代表真实售价', sort: 3 },
];

const OPS = [
  { op: 'llm', model: 'qwen-plus（演示）', w: 6 },
  { op: 'tts', model: 'cosyvoice（演示）', w: 3 },
  { op: 'asr', model: 'qwen3-asr（演示）', w: 3 },
  { op: 'summary', model: 'qwen-turbo（演示）', w: 1 },
  { op: 'vision', model: 'qwen-vl（演示）', w: 1 },
  { op: 'search', model: '记忆服务（演示）', w: 1 },
];

function pickOp(r) {
  const total = OPS.reduce((n, o) => n + o.w, 0);
  let x = r() * total;
  for (const o of OPS) { x -= o.w; if (x <= 0) return o; }
  return OPS[0];
}

/** 近 30 天的调用明细（createdAt 为秒级时间戳，与原组件的读取方式一致） */
function buildCalls(userId, now, seedNum, perDay) {
  const r = rng(seedNum);
  const rows = [];
  let n = 0;
  for (let d = 29; d >= 0; d--) {
    const count = Math.max(0, Math.round(perDay * (0.4 + r())));
    for (let i = 0; i < count; i++) {
      const o = pickOp(r);
      const ts = now - d * DAY - Math.floor(r() * 20 * 3600000);
      if (ts > now) continue;
      const inTok = o.op === 'llm' || o.op === 'summary' || o.op === 'vision' ? Math.round(300 + r() * 2400) : null;
      const outTok = inTok ? Math.round(40 + r() * 400) : null;
      const units = o.op === 'tts' ? Math.round(20 + r() * 180) : o.op === 'asr' ? Math.round(3 + r() * 40) : null;
      const points = Number((0.02 + r() * 1.6).toFixed(4));
      const legacy = r() < 0.25;
      n += 1;
      rows.push({
        id: `demo-call-${userId.slice(-4)}-${String(n).padStart(4, '0')}`,
        userId,
        createdAt: Math.floor(ts / 1000),
        operation: o.op,
        model: o.model,
        points,
        paidAmountCny: legacy ? null : Number((points * 0.01).toFixed(6)),
        legacyPoints: legacy ? points : 0,
        reservedPoints: 0,
        state: d === 0 && i === 0 ? 'pending' : 'settled',
        inputTokens: inTok,
        outputTokens: outTok,
        cachedTokens: inTok ? Math.round(inTok * r() * 0.3) : null,
        units,
        unit: o.op === 'tts' ? 'weighted_character' : o.op === 'asr' ? 'audio_second' : null,
      });
    }
  }
  return rows.sort((a, b) => b.createdAt - a.createdAt);
}

function buildMemoryBills(userId, now, seedNum) {
  const r = rng(seedNum);
  const ops = ['fact', 'portrait', 'search', 'storage'];
  const states = ['settled', 'settled', 'settled', 'refunded', 'pending'];
  const rows = [];
  for (let i = 0; i < 23; i++) {
    const amount = Number((0.00002 + r() * 0.002).toFixed(8));
    rows.push({
      id: `demo-mem-${userId.slice(-4)}-${i + 1}`,
      userId,
      createdAt: iso(now - i * 0.9 * DAY - Math.floor(r() * 8 * 3600000)),
      operation: ops[Math.floor(r() * ops.length)],
      amountCny: amount,
      chargedPoints: Number((amount * 100).toFixed(4)),
      state: i === 0 ? 'reserved' : states[Math.floor(r() * states.length)],
    });
  }
  return rows;
}

function order(no, userId, pkg, status, createdMs, channel = 'alipay') {
  return {
    outTradeNo: no, userId, packageId: pkg.id, packageName: pkg.name, amountCents: pkg.amountCents, quotaPoints: pkg.quotaPoints,
    channel, status, createdAt: iso(createdMs),
    paidAt: status === 'delivered' || status === 'paid' ? createdMs + 40000 : null,
    deliveredAt: status === 'delivered' ? createdMs + 45000 : null,
  };
}

export function buildBillingSeed(now = Date.now()) {
  const [a, b, c] = DEMO_PACKAGES;
  const u = DEMO_USERS.user.id;
  const adm = DEMO_USERS.admin.id;
  const orders = [
    order('DEMO20260001001', u, b, 'delivered', now - 26 * DAY),
    order('DEMO20260001002', u, a, 'closed', now - 19 * DAY),
    order('DEMO20260001003', u, c, 'delivered', now - 12 * DAY),
    order('DEMO20260001004', u, a, 'delivered', now - 5 * DAY),
    order('DEMO20260001005', u, b, 'refunded', now - 3 * DAY),
    order('DEMO20260009001', adm, c, 'delivered', now - 40 * DAY),
  ];
  // 再补几条早期订单，便于演示分页
  for (let i = 0; i < 8; i++) {
    orders.push(order(`DEMO2025000${2000 + i}`, u, i % 2 ? a : b, i === 3 ? 'closed' : 'delivered', now - (35 + i * 6) * DAY));
  }
  return {
    payPackages: DEMO_PACKAGES.map((p) => ({ ...p })),
    payOrders: orders,
    payCalls: buildCalls(u, now, 1001, 5).concat(buildCalls(adm, now, 9001, 2)),
    memoryBills: buildMemoryBills(u, now, 77).concat(buildMemoryBills(adm, now, 99).slice(0, 4)),
  };
}

seed(() => buildBillingSeed());
