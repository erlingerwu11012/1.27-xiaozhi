/**
 * 官方视觉角色包（/role-packs/*）。壁纸包（/wallpaper-packs/*）结构相同，复用这里的 registerPackRoutes。
 *
 * 调用方：views/RolePackCatalog.vue、views/WallpaperPackCatalog.vue（模块回调 res.data，页面读 code / data / errorCode / msg）。
 * - GET  /catalog              → data: [{ packId, displayName, description, version, size, previewImageUrl, previewVideoUrl, publishedAt, ... }]
 * - GET  /:packId              → data: 包详情（含适配型号、最低固件等）
 * - POST /:packId/deploy/:deviceId → data: 任务 { taskId, packId, deviceId, state, progress, errorCode }
 * - GET  /tasks/:taskId        → data: 任务（状态按创建后经过的时间推进：queued → sent → downloading → verifying → applying → succeeded）
 * - POST /inspect (FormData spineBin)      → data: 识别结果（管理员）
 * - POST /publish (FormData displayName, description, spineBin, previewImage, previewVideo) → 新包（管理员）
 * - POST /:packId/disable                  → 停用（管理员）
 * 错误码沿用 visualOta.error.*（E_BUSY / E_BOARD / E_SIZE / E_BUNDLE），页面用 resolveOtaApiMessage 翻译。
 * 全部是演示：没有任何设备收到内容，识别结果根据文件名和大小生成。
 */
import { route, ok, raw, fail, requireAdmin, nextId, nowStr } from '../core';
import { ensureVisualPacks } from '../seed/visualPacks';
import { placeholderImage } from '../media';

const STEPS = [['queued', 0], ['sent', 10], ['downloading', 35], ['downloading', 70], ['verifying', 90], ['applying', 96], ['succeeded', 100]];
const STEP_MS = 2000;
const FINAL = ['succeeded', 'failed', 'cancelled'];

/**
 * OTA 业务错误：带 errorCode，页面可按 visualOta.error.<code> 翻译；
 * 原 API 模块对 code≠0 不回调页面，而是由请求层直接弹出 msg，所以 msg 写成用户能看懂的话。
 */
const OTA_MSG = {
  E_BUSY: '设备正忙或已有进行中的下载任务，请稍后再试',
  E_BOARD: '当前设备型号不支持这个包',
  E_SIZE: '文件大小超出限制',
  E_BUNDLE: '文件格式无效或已损坏',
  E_TASK_MISMATCH: '任务不存在或已过期，请重新下载',
};
function otaFail(code) {
  return raw({ code: 1, msg: OTA_MSG[code] || '操作失败，请稍后重试', errorCode: code });
}

function taskView(t) {
  const step = Math.min(STEPS.length - 1, Math.floor((Date.now() - t.createdMs) / STEP_MS));
  const [state, progress] = STEPS[step];
  return { taskId: t.taskId, packId: t.packId, deviceId: t.deviceId, state, progress, errorCode: 'none', createdAt: t.createdAt };
}

function slug(name) {
  return String(name || '').replace(/\.[^.]+$/, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

/**
 * @param {object} cfg
 * @param {string} cfg.base       '/role-packs' | '/wallpaper-packs'
 * @param {string} cfg.key        数据库集合名
 * @param {string} cfg.kind       任务类型
 * @param {number} cfg.maxSize    包文件大小上限（字节）
 * @param {Function} cfg.meta     (file) => 识别结果中与类型相关的字段
 * @param {Function} cfg.row      (pack) => 目录行
 */
export function registerPackRoutes(cfg) {
  const packs = (db) => ensureVisualPacks(db)[cfg.key];
  const findPack = (db, id) => packs(db).find((p) => p.packId === id);

  function inspectFile(file) {
    if (!file || !file.__file) return { err: fail('请选择包文件') };
    if (!/\.bin$/i.test(file.name || '')) return { err: otaFail('E_BUNDLE') };
    if (file.size > cfg.maxSize) return { err: otaFail('E_SIZE') };
    const id = slug(file.name);
    return { meta: { packId: `demo-${id || 'pack-' + nextId()}`, version: '1.0.0', size: file.size, ...cfg.meta(file) } };
  }

  route('GET', `${cfg.base}/catalog`, ({ db, scenario }) => {
    if (scenario.data === 'empty') return ok([]);
    return ok(packs(db).filter((p) => p.status === 'published').map(cfg.row));
  });

  route('GET', `${cfg.base}/:packId`, ({ db, params, user }) => {
    const p = findPack(db, params.packId);
    if (!p || (p.status !== 'published' && user.superAdmin !== 1)) return fail('内容不存在或已停用');
    const { status, ...rest } = p;
    return ok({ ...rest, status });
  });

  route('POST', `${cfg.base}/:packId/deploy/:deviceId`, ({ db, params, user }) => {
    const p = findPack(db, params.packId);
    if (!p || p.status !== 'published') return fail('内容不存在或已停用');
    const d = (db.devices || []).find((x) => x.id === params.deviceId && x.userId === user.id);
    if (!d) return fail('设备不存在或不属于当前账号');
    const boards = p.defaultSupportedBoards;
    if (Array.isArray(boards) && boards.length && !boards.includes(d.board)) return otaFail('E_BOARD');
    const running = db.visualTasks.find((t) => t.kind === cfg.kind && t.deviceId === d.id && !FINAL.includes(taskView(t).state));
    if (running) return otaFail('E_BUSY');
    const t = { taskId: `demo-task-${nextId()}`, kind: cfg.kind, ownerId: user.id, packId: p.packId, deviceId: d.id, createdAt: nowStr(), createdMs: Date.now() };
    db.visualTasks.push(t);
    db.visualTasks = db.visualTasks.slice(-50);
    return ok(taskView(t), '已创建下载任务（演示：不会向设备下发任何内容）');
  });

  route('GET', `${cfg.base}/tasks/:taskId`, ({ db, params, user }) => {
    const t = ensureVisualPacks(db).visualTasks.find((x) => x.taskId === params.taskId && x.kind === cfg.kind && x.ownerId === user.id);
    if (!t) return otaFail('E_TASK_MISMATCH');
    return ok(taskView(t), '演示进度');
  });

  route('POST', `${cfg.base}/inspect`, ({ body, user }) => {
    const denied = requireAdmin(user); if (denied) return denied;
    const { err, meta } = inspectFile(body.spineBin);
    if (err) return err;
    return ok(meta, '演示：识别结果根据文件名和大小生成');
  });

  route('POST', `${cfg.base}/publish`, ({ db, body, user }) => {
    const denied = requireAdmin(user); if (denied) return denied;
    const name = String(body.displayName || '').trim();
    if (!name) return fail('请填写显示名称');
    const { err, meta } = inspectFile(body.spineBin);
    if (err) return err;
    const existing = findPack(db, meta.packId);
    const pack = {
      ...meta,
      displayName: name,
      description: String(body.description || ''),
      previewImageUrl: placeholderImage(name.slice(0, 12), 480, 300, '#E4EEF4'),
      previewVideoUrl: body.previewVideo && body.previewVideo.__file ? `${cfg.base}/media/${meta.packId}.mp4` : '',
      status: 'published',
      publishedAt: nowStr(),
    };
    if (existing) {
      // 同一包 ID 再次发布视为新版本（待确认：真实服务是否覆盖旧版本）
      const [maj, min, patch] = String(existing.version || '1.0.0').split('.').map((n) => Number(n) || 0);
      Object.assign(existing, pack, { version: `${maj}.${min}.${patch + 1}` });
      return ok(cfg.row(existing), '已发布（演示）');
    }
    packs(db).unshift(pack);
    return ok(cfg.row(pack), '已发布（演示）');
  });

  route('POST', `${cfg.base}/:packId/disable`, ({ db, params, user }) => {
    const denied = requireAdmin(user); if (denied) return denied;
    const p = findPack(db, params.packId);
    if (!p) return fail('内容不存在');
    p.status = 'disabled';
    return ok(null, '已停用（演示）');
  });
}

registerPackRoutes({
  base: '/role-packs',
  key: 'rolePacks',
  kind: 'role',
  maxSize: 4194304,
  meta: () => ({ spineRuntimeVersion: '4.1', format: 'spine-mmap', defaultSupportedBoards: ['xiaonian-desk'], minFirmware: '1.6.0' }),
  row: (p) => ({
    packId: p.packId, displayName: p.displayName, description: p.description, version: p.version, size: p.size,
    previewImageUrl: p.previewImageUrl, previewVideoUrl: p.previewVideoUrl, defaultSupportedBoards: p.defaultSupportedBoards,
    minFirmware: p.minFirmware, publishedAt: p.publishedAt,
  }),
});
