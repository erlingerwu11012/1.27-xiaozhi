/**
 * 媒体地址与下载的统一出口（音频回放、聊天记录下载等原本直接拼服务端 URL 的地方）。
 * - real 模式：原样返回服务端地址 / 用 window.open 打开，与原代码行为一致；
 * - mock 模式：不访问任何服务端地址，返回浏览器内生成的演示音频，或下载一份写明“演示”的文本文件。
 * 判断使用构建期常量，real 构建不会包含演示代码。
 */
const MOCK = process.env.VUE_APP_DATA_MODE !== 'real';
const mockMedia = process.env.VUE_APP_DATA_MODE !== 'real' ? require('../mock/media') : null;

/** 可直接赋给 <audio>.src / new Audio() 的地址 */
export function playableUrl(url) {
  return MOCK ? mockMedia.toneUrlOnce() : url;
}

/** 打开下载地址；mock 模式生成演示文件 */
export function openDownload(url, filename = '演示文件.txt', mockText = '') {
  if (MOCK) {
    mockMedia.downloadText(filename, mockText || `演示数据：这是前端演示模式生成的文件，并非真实下载内容。\n原下载地址：${url}\n`);
    return;
  }
  window.open(url, '_blank');
}

/** 演示用占位图（mock 模式）；real 模式原样返回 */
export function imageUrl(url, label) {
  return MOCK && !/^(data:|blob:)/.test(String(url || '')) ? mockMedia.placeholderImage(label || '演示图片') : url;
}

export const IS_MOCK = MOCK;
