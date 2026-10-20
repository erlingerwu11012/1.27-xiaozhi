/**
 * 人员身份演示数据：成员（/user-identities）、人脸资料与设备采集草稿（/face）。
 * 声纹记录本身属于 /agent/voice-print（agents 模块的 seed），这里只保存“成员 ↔ 声纹 id”的绑定。
 * 字段名与原页面读取的一致：成员 userId / displayName / faceProfileIds / voiceprintIds；
 * 人脸 user_id / display_name / status(draft|active) / face_count / created_at；
 * 采集草稿 session_id / status(collecting|draft_ready|expired) / accepted_count / has_preview / created_at。
 */
import { seed, minutesAgo, nowStr } from '../core';
import { DEMO_USERS } from './core';

const daysAgo = (d, h = 10) => nowStr(new Date(Date.now() - d * 86400000 - h * 3600000));
const U = DEMO_USERS.user.id;
const A = DEMO_USERS.admin.id;

/** 初始数据；导出给 handler：浏览器里已有旧版演示数据库时按需补上这些集合 */
export const buildIdentitySeed = () => ({
  identities: [
    { userId: 'demo-p-1', ownerId: U, displayName: '妈妈（演示）', faceProfileIds: ['demo-face-1'], voiceprintIds: ['demo-vp-1'], createdAt: daysAgo(20) },
    { userId: 'demo-p-2', ownerId: U, displayName: '小宇（演示）', faceProfileIds: ['demo-face-2'], voiceprintIds: [], createdAt: daysAgo(18) },
    { userId: 'demo-p-3', ownerId: U, displayName: '外婆（演示）', faceProfileIds: [], voiceprintIds: [], createdAt: daysAgo(6) },
    { userId: 'demo-p-9', ownerId: A, displayName: '联调测试员（演示）', faceProfileIds: [], voiceprintIds: [], createdAt: daysAgo(40) },
  ],
  faceProfiles: [
    { user_id: 'demo-face-1', ownerId: U, display_name: '妈妈（演示）', status: 'active', face_count: 4, created_at: daysAgo(20, 2) },
    { user_id: 'demo-face-2', ownerId: U, display_name: '小宇（演示）', status: 'active', face_count: 3, created_at: daysAgo(17, 5) },
    { user_id: 'demo-face-3', ownerId: U, display_name: '爷爷（演示）', status: 'active', face_count: 2, created_at: daysAgo(9, 3) },
  ],
  faceEnrollments: [
    { session_id: 'demo-enr-1', ownerId: U, device_id: 'demo-d-1', status: 'draft_ready', accepted_count: 5, has_preview: true, created_at: minutesAgo(35) },
    { session_id: 'demo-enr-2', ownerId: U, device_id: 'demo-d-2', status: 'collecting', accepted_count: 1, has_preview: false, created_at: minutesAgo(4) },
  ],
});

export const IDENTITY_KEYS = ['identities', 'faceProfiles', 'faceEnrollments'];

/** 浏览器里已有旧版演示数据库（本模块上线前生成）时，补上缺少的集合 */
export function ensureIdentity(db) {
  if (IDENTITY_KEYS.every((k) => db[k])) return db;
  const fresh = buildIdentitySeed();
  IDENTITY_KEYS.forEach((k) => { if (!db[k]) db[k] = fresh[k]; });
  return db;
}

seed(buildIdentitySeed);
