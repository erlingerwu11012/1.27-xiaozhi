/**
 * 官方壁纸包（/wallpaper-packs/*）：接口结构与视觉角色包相同，见 handlers/rolePack.js 的 registerPackRoutes。
 * 调用方：views/WallpaperPackCatalog.vue。识别结果字段：packId / version / defaultId / itemCount / size。
 */
import { registerPackRoutes } from './rolePack';

registerPackRoutes({
  base: '/wallpaper-packs',
  key: 'wallpaperPacks',
  kind: 'wallpaper',
  maxSize: 2097152,
  meta: (file) => ({ defaultId: 'wp_01', itemCount: Math.max(1, Math.min(16, Math.round((file.size || 0) / 131072))) }),
  row: (p) => ({
    packId: p.packId, displayName: p.displayName, description: p.description, version: p.version, size: p.size,
    defaultId: p.defaultId, itemCount: p.itemCount, previewImageUrl: p.previewImageUrl, previewVideoUrl: p.previewVideoUrl,
    publishedAt: p.publishedAt,
  }),
});
