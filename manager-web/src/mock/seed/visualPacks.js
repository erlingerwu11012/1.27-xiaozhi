/**
 * 官方视觉角色包（/role-packs）与壁纸包（/wallpaper-packs）的演示数据。
 * 封面是浏览器内生成的占位图（data URL）；演示视频只保留一个路径，演示模式下页面不会加载它。
 * 下载任务（visualTasks）在运行时创建，状态按创建后经过的时间推进，见 handlers/visualPack.js。
 */
import { seed, nowStr } from '../core';
import { placeholderImage } from '../media';

const daysAgo = (d, h = 10) => nowStr(new Date(Date.now() - d * 86400000 - h * 3600000));

export const buildVisualPackSeed = () => ({
  rolePacks: [
    {
      packId: 'demo-role-desk', displayName: '书桌小念（演示）', description: '默认的桌面陪伴形象，待机时会眨眼、偶尔伸个懒腰。（演示）',
      version: '1.3.0', size: 2621440, spineRuntimeVersion: '4.1', format: 'spine-mmap', defaultSupportedBoards: ['xiaonian-desk'], minFirmware: '1.6.0',
      previewImageUrl: placeholderImage('书桌小念', 480, 300, '#DCE7EF'), previewVideoUrl: '/role-packs/media/demo-role-desk.mp4',
      status: 'published', publishedAt: daysAgo(40),
    },
    {
      packId: 'demo-role-cat', displayName: '晚安猫（演示）', description: '偏安静的夜间形象，动作幅度小，适合放在卧室。（演示）',
      version: '1.0.2', size: 1887436, spineRuntimeVersion: '4.1', format: 'spine-mmap', defaultSupportedBoards: ['xiaonian-desk'], minFirmware: '1.6.0',
      previewImageUrl: placeholderImage('晚安猫', 480, 300, '#E4E8F1'), previewVideoUrl: '',
      status: 'published', publishedAt: daysAgo(22),
    },
    {
      packId: 'demo-role-study', displayName: '学习搭子（演示）', description: '戴眼镜的学习伙伴形象，专注模式时会安静地看书。（演示）',
      version: '0.9.0', size: 3355443, spineRuntimeVersion: '4.1', format: 'spine-mmap', defaultSupportedBoards: ['xiaonian-desk', 'esp32-s3-box'], minFirmware: '1.6.2',
      previewImageUrl: placeholderImage('学习搭子', 480, 300, '#E2ECE6'), previewVideoUrl: '/role-packs/media/demo-role-study.mp4',
      status: 'published', publishedAt: daysAgo(8),
    },
  ],
  wallpaperPacks: [
    {
      packId: 'demo-wp-lake', displayName: '湖边四季（演示）', description: '春夏秋冬四组湖边风景，每组两张。（演示）',
      version: '1.1.0', size: 1468006, defaultId: 'lake_spring_1', itemCount: 8, previewImageUrl: placeholderImage('湖边四季', 480, 300, '#DCE7EF'),
      previewVideoUrl: '', status: 'published', publishedAt: daysAgo(30),
    },
    {
      packId: 'demo-wp-paper', displayName: '纸张纹理（演示）', description: '浅色纸张纹理，屏幕上的文字更容易看清。（演示）',
      version: '1.0.0', size: 734003, defaultId: 'paper_01', itemCount: 5, previewImageUrl: placeholderImage('纸张纹理', 480, 300, '#EFEBE3'),
      previewVideoUrl: '/wallpaper-packs/media/demo-wp-paper.mp4', status: 'published', publishedAt: daysAgo(12),
    },
    {
      packId: 'demo-wp-night', displayName: '夜间低亮（演示）', description: '深色低亮度壁纸，夜里放在床头不刺眼。（演示）',
      version: '1.0.1', size: 524288, defaultId: 'night_01', itemCount: 4, previewImageUrl: placeholderImage('夜间低亮', 480, 300, '#D9DEE6'),
      previewVideoUrl: '', status: 'published', publishedAt: daysAgo(3),
    },
  ],
  visualTasks: [],
  // 设备自定义图片（DeviceAssetsDialog）：deviceId → [{ id, deviceId, fileType, version, fileName, fileUrl, createDate }]
  deviceAssets: {
    'demo-d-1': [
      { id: 'demo-asset-1', deviceId: 'demo-d-1', fileType: 'wallpaper', version: 1, fileName: '书桌壁纸（演示）.png', fileUrl: placeholderImage('壁纸图片', 240, 240, '#DCE7EF'), createDate: daysAgo(5) },
      { id: 'demo-asset-2', deviceId: 'demo-d-1', fileType: 'emoji', version: 1, fileName: '开心（演示）.png', fileUrl: placeholderImage('表情图片', 240, 240, '#EFE7DA'), createDate: daysAgo(2) },
    ],
  },
});

export const VISUAL_PACK_KEYS = ['rolePacks', 'wallpaperPacks', 'visualTasks'];

/** 浏览器里已有旧版演示数据库（本模块上线前生成）时，补上缺少的集合 */
export function ensureVisualPacks(db) {
  if (VISUAL_PACK_KEYS.every((k) => db[k])) return db;
  const fresh = buildVisualPackSeed();
  VISUAL_PACK_KEYS.forEach((k) => { if (!db[k]) db[k] = fresh[k]; });
  return db;
}

seed(buildVisualPackSeed);
