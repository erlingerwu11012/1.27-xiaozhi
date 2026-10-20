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

/* ───── 设备视觉资源（DeviceAssetsDialog）─────
 * 调用方 components/DeviceAssetsDialog.vue（回调 res，读 res.data.code / res.data.data / res.data.msg）：
 * - GET  /device/assets/list?device_id=        → data: [{ id, deviceId, fileType: emoji|wallpaper, fileUrl, version, fileName, createDate }]
 * - POST /device/assets/upload (FormData device_id, file_type, file) → 新记录；同一设备同一类型 version 递增（待确认）
 * - POST /device/assets/sync-assets?device_id=  → 只记录同步时间，不向设备下发任何内容
 * fileUrl 是浏览器内生成的占位图（data URL），上传的文件不离开本机。 */

const ASSET_TYPES = ['emoji', 'wallpaper'];

route('GET', '/device/assets/list', ({ query, db, user, scenario }) => {
  const d = ownDevice(db, user, query.device_id);
  if (!d) return fail('设备不存在或无权查看');
  if (scenario.data === 'empty') return ok([]);
  db.deviceAssets = db.deviceAssets || {};
  return ok((db.deviceAssets[d.id] || []).filter((x) => x && x.fileUrl).slice().reverse());
});

route('POST', '/device/assets/upload', ({ body, db, user }) => {
  const d = ownDevice(db, user, body.device_id);
  if (!d) return fail('设备不存在或无权操作');
  const fileType = body.file_type;
  if (!ASSET_TYPES.includes(fileType)) return fail('请选择图片类型');
  const file = body.file;
  if (!file || !file.__file) return fail('请选择图片');
  if (!/^image\/(jpeg|jpg|png)$/.test(file.type || '')) return fail('仅支持 JPG、PNG 格式');
  if (file.size >= 5 * 1024 * 1024) return fail('图片大小不能超过 5MB');
  db.deviceAssets = db.deviceAssets || {};
  const list = (db.deviceAssets[d.id] || []).filter((x) => x && x.fileUrl);
  db.deviceAssets[d.id] = list;
  const version = list.filter((x) => x.fileType === fileType).reduce((m, x) => Math.max(m, Number(x.version) || 0), 0) + 1;
  const label = fileType === 'emoji' ? '表情图片' : '壁纸图片';
  list.push({
    id: `demo-asset-${nextId()}`, deviceId: d.id, fileType, version, fileName: file.name || `${label}.png`,
    fileUrl: placeholderImage(label, 240, 240, fileType === 'emoji' ? '#EFE7DA' : '#DCE7EF'), createDate: nowStr(),
  });
  return ok(null, '已上传（演示：文件没有离开本机）');
});

route('POST', '/device/assets/sync-assets', ({ query, db, user }) => {
  const d = ownDevice(db, user, query.device_id);
  if (!d) return fail('设备不存在或无权操作');
  db.deviceAssetSync = db.deviceAssetSync || {};
  db.deviceAssetSync[d.id] = nowStr();
  return ok(null, '已提交同步（演示：没有向设备下发任何内容）');
});
