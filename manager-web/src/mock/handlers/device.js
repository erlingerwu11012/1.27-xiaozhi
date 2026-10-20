/**
 * 设备（/device/*）：绑定、解绑、备注、手动添加、设备视觉资源。
 * 演示绑定码见 seed/core.js 的 bindCodes（123456、246810、135790、888888），
 * 恢复连接与绑定在原代码里走同一个接口 POST /device/bind/{agentId}/{code}。
 * 不会向任何设备下发指令；“同步资源”只改本地演示数据的状态。
 */
import { route, ok, fail, nowStr, nextId } from '../core';
import { findOwnAgent } from './agent';
import { placeholderImage } from '../media';

const ownDevice = (db, user, id) => db.devices.find((d) => d.id === id && (d.userId === user.id || user.superAdmin === 1));

function randomMac() {
  const hex = () => Math.floor(Math.random() * 256).toString(16).toUpperCase().padStart(2, '0');
  return ['02', '00', '5E', hex(), hex(), hex()].join(':');
}

route('GET', '/device/bind/:agentId', ({ params, db, user }) => {
  const a = findOwnAgent(db, user, params.agentId);
  if (!a) return fail('智能体不存在或无权查看');
  return ok(db.devices.filter((d) => d.agentId === a.id).map((d) => ({
    id: d.id, agentId: d.agentId, board: d.board, appVersion: d.appVersion, macAddress: d.macAddress,
    alias: d.alias, createDate: d.createDate, lastConnectedAt: d.lastConnectedAt, autoUpdate: d.autoUpdate,
  })));
});

route('POST', '/device/bind/:agentId/:code', ({ params, db, user }) => {
  const a = findOwnAgent(db, user, params.agentId);
  if (!a) return fail('智能体不存在或无权操作');
  if (!/^\d{6}$/.test(params.code)) return fail('请输入 6 位数字验证码');
  if (!db.bindCodes.includes(params.code)) return fail('验证码无效或已过期，请让设备重新播报（演示可用：123456、246810、135790、888888）');
  db.bindCodes = db.bindCodes.filter((c) => c !== params.code);
  db.devices.push({
    id: `demo-d-${nextId()}`, agentId: a.id, userId: user.id, board: 'xiaonian-desk', appVersion: '1.6.2',
    macAddress: randomMac(), alias: '', createDate: nowStr(), lastConnectedAt: null, autoUpdate: 1,
  });
  return ok(null);
});

/** 原接口一次解绑一台，body: { deviceId } */
route('POST', '/device/unbind', ({ body, db, user }) => {
  const d = ownDevice(db, user, body.deviceId);
  if (!d) return fail('设备不存在或无权操作');
  db.devices = db.devices.filter((x) => x.id !== d.id);
  return ok(null);
});

route('PUT', '/device/update/:id', ({ params, body, db, user }) => {
  const d = ownDevice(db, user, params.id);
  if (!d) return fail('设备不存在或无权操作');
  if (body.alias !== undefined) {
    if (String(body.alias).length > 64) return fail('备注不能超过 64 个字符');
    d.alias = String(body.alias);
  }
  if (body.autoUpdate !== undefined) d.autoUpdate = Number(body.autoUpdate);
  return ok(null);
});

route('POST', '/device/manual-add', ({ body, db, user }) => {
  const a = findOwnAgent(db, user, body.agentId);
  if (!a) return fail('智能体不存在或无权操作');
  if (!(db.dictByType.FIRMWARE_TYPE || []).some((t) => t.key === body.board)) return fail('请选择设备类型');
  if (!body.appVersion) return fail('请输入固件版本');
  const mac = String(body.macAddress || '').toUpperCase().replace(/-/g, ':');
  if (!/^([0-9A-F]{2}:){5}[0-9A-F]{2}$/.test(mac)) return fail('MAC 地址格式不正确');
  if (db.devices.some((d) => d.macAddress === mac)) return fail('该 MAC 地址的设备已存在');
  db.devices.push({
    id: `demo-d-${nextId()}`, agentId: a.id, userId: user.id, board: body.board, appVersion: body.appVersion,
    macAddress: mac, alias: '', createDate: nowStr(), lastConnectedAt: null, autoUpdate: 1,
  });
  return ok(null);
});

/* ───── 设备视觉资源（DeviceAssetsDialog）───── */

route('GET', '/device/assets/list', ({ query, db, user }) => {
  const d = ownDevice(db, user, query.device_id);
  if (!d) return fail('设备不存在或无权查看');
  db.deviceAssets = db.deviceAssets || {};
  return ok(db.deviceAssets[d.id] || []);
});

route('POST', '/device/assets/upload', ({ body, db, user }) => {
  const d = ownDevice(db, user, body.device_id || body.deviceId);
  if (!d) return fail('设备不存在或无权操作');
  const file = body.file || {};
  db.deviceAssets = db.deviceAssets || {};
  const list = db.deviceAssets[d.id] || (db.deviceAssets[d.id] = []);
  list.push({
    id: `demo-asset-${nextId()}`, device_id: d.id, file_type: body.file_type || body.fileType || 'image',
    file_name: file.name || '演示图片.png', file_size: file.size || 0,
    url: placeholderImage(file.name || '演示资源', 240, 240), status: 'pending', created_at: nowStr(),
  });
  return ok(null, '已上传（演示：文件未离开本机）');
});

route('POST', '/device/assets/sync-assets', ({ query, db, user }) => {
  const d = ownDevice(db, user, query.device_id);
  if (!d) return fail('设备不存在或无权操作');
  ((db.deviceAssets || {})[d.id] || []).forEach((x) => { x.status = 'synced'; });
  return ok(null, '已同步（演示：未向设备下发）');
});
