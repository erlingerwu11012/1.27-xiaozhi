/**
 * 改版新增 / 覆盖的文案。规则：
 * - 新文案一律用 xn. 前缀，避免与原文案和 OTA 文案检查（rolePack. / wallpaperPack. / visualOta. / deviceAssets.）冲突；
 * - 允许覆盖原有 key 的取值（例如把“one-api / 缓存”等实现细节改成用户能理解的说法），key 本身不变；
 * - 每个分组一个文件，导出 { zh_CN: {...}, en: {...} }。
 * zh_TW 使用简体覆盖、de / vi 使用英文覆盖，未覆盖的仍走原文案。
 */
import shell from './shell';
import home from './home';

const groups = [shell, home];
const req = require.context('./groups', false, /\.js$/);
req.keys().forEach((k) => groups.push(req(k).default || req(k)));

function merge(lang) {
  return groups.reduce((acc, g) => Object.assign(acc, g[lang] || {}), {});
}

export const redesignZh = merge('zh_CN');
export const redesignEn = merge('en');
