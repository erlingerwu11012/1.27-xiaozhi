/**
 * 演示用的二进制内容：全部在浏览器内生成，不读取任何真实文件或网络资源。
 */

/** 图形验证码（SVG），图上明确写着“演示” */
export function captchaBlob(code) {
  const chars = String(code).split('').map((ch, i) =>
    `<text x="${14 + i * 22}" y="${28 + (i % 2 ? -3 : 3)}" font-size="22" font-family="monospace" font-weight="700" fill="#1C2A3D" transform="rotate(${(i % 2 ? 8 : -8)} ${14 + i * 22} 24)">${ch}</text>`).join('');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40" viewBox="0 0 120 40">
<rect width="120" height="40" rx="6" fill="#E9EFF4"/>
<path d="M4 30 C30 8, 60 36, 116 12" stroke="#9DB4C6" stroke-width="1.5" fill="none"/>
${chars}<text x="116" y="37" font-size="8" text-anchor="end" fill="#874C1B">演示</text></svg>`;
  return new Blob([svg], { type: 'image/svg+xml' });
}

/** 生成一段短提示音（WAV），用于试听、聊天语音回放等 */
export function toneWavBlob(seconds = 1.2, freq = 523.25) {
  const rate = 16000;
  const n = Math.floor(rate * seconds);
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); str(8, 'WAVE'); str(12, 'fmt ');
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, 'data'); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const t = i / rate;
    const env = Math.min(1, t * 20) * Math.min(1, (seconds - t) * 6);
    v.setInt16(44 + i * 2, Math.sin(2 * Math.PI * freq * t) * 0.25 * env * 32767, true);
  }
  return new Blob([buf], { type: 'audio/wav' });
}

let toneUrl = null;
/** 可直接赋给 <audio>.src 的演示音频地址 */
export function toneUrlOnce() {
  if (!toneUrl) toneUrl = URL.createObjectURL(toneWavBlob());
  return toneUrl;
}

/** 占位图（SVG data URL），图上写明演示用途 */
export function placeholderImage(label = '演示图片', w = 320, h = 240, tint = '#DCE7EF') {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
<rect width="${w}" height="${h}" fill="${tint}"/>
<rect x="${w / 2 - 34}" y="${h / 2 - 40}" width="68" height="52" rx="8" fill="none" stroke="#5B697C" stroke-width="2"/>
<circle cx="${w / 2 - 14}" cy="${h / 2 - 22}" r="6" fill="#5B697C"/>
<path d="M${w / 2 - 28} ${h / 2 + 4} l18 -16 l14 12 l10 -8 l14 12" stroke="#5B697C" stroke-width="2" fill="none"/>
<text x="${w / 2}" y="${h / 2 + 40}" font-size="14" text-anchor="middle" fill="#44546A" font-family="sans-serif">${label}</text>
<text x="${w - 8}" y="${h - 8}" font-size="11" text-anchor="end" fill="#874C1B" font-family="sans-serif">演示数据</text></svg>`;
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}

/** 在浏览器内生成并下载一个演示文件 */
export function downloadText(filename, text, type = 'text/plain;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
