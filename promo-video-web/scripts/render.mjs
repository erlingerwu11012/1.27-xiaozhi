#!/usr/bin/env node
/**
 * 可复现导出：无头 Chromium（软件 WebGL，SwiftShader）逐帧调用 window.__promo.renderFrame(t)，
 * 写出 PNG 序列，再用 ffmpeg 编码为 H.264 MP4（1920×1080，30fps，yuv420p）。
 *
 * 用法（先 npm run build）：
 *   node scripts/render.mjs --dist dist --from 0 --to 7 --fps 30 --out output/opening-7s.mp4
 *   node scripts/render.mjs --dist dist --stills            # 输出关键画面 PNG 到 output/stills
 *   node scripts/render.mjs --dist dist --at 6.6            # 单帧 → output/frame_6.600.png
 * 选项：--no-subtitles  --frames-dir <目录>  --keep-frames  --gpu（改用本机 GPU，速度快但跨机器像素可能略有差异）
 */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { chromium } from 'playwright';

const argv = process.argv.slice(2);
const arg = (k, d) => {
  const i = argv.indexOf(`--${k}`);
  return i >= 0 ? argv[i + 1] : d;
};
const flag = (k) => argv.includes(`--${k}`);

const dist = path.resolve(arg('dist', 'dist'));
const outDir = path.resolve('output');
const subtitles = !flag('no-subtitles');
fs.mkdirSync(outDir, { recursive: true });
if (!fs.existsSync(path.join(dist, 'index.html'))) {
  console.error(`未找到 ${dist}/index.html，请先运行 npm run build`);
  process.exit(1);
}

const types = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.png': 'image/png',
  '.json': 'application/json',
  '.atlas': 'text/plain',
  '.skel': 'application/octet-stream',
  '.ogg': 'audio/ogg',
  '.wav': 'audio/wav',
  '.mp3': 'audio/mpeg',
};
const server = http
  .createServer((req, res) => {
    const p = path.join(dist, decodeURIComponent(req.url.split('?')[0]));
    if (!p.startsWith(dist)) return res.writeHead(403).end();
    fs.readFile(p.endsWith(path.sep) ? path.join(p, 'index.html') : p, (err, data) => {
      if (err) return res.writeHead(404).end();
      res.writeHead(200, { 'content-type': types[path.extname(p)] ?? 'application/octet-stream' });
      res.end(data);
    });
  })
  .listen(0, '127.0.0.1');
await new Promise((r) => server.once('listening', r));
const url = `http://127.0.0.1:${server.address().port}/index.html?mode=export`;

const gl = flag('gpu') ? [] : ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'];
const browser = await chromium.launch({ args: [...gl, '--ignore-gpu-blocklist', '--force-color-profile=srgb'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
page.on('console', (m) => m.type() === 'error' && console.error('[page]', m.text()));
await page.goto(url);
await page.waitForFunction(() => window.__promo && (window.__promo.ready || window.__promo.error), null, {
  timeout: 180000,
});
const err = await page.evaluate(() => window.__promo.error);
if (err) {
  console.error(err);
  process.exit(1);
}
console.log('素材已加载：', JSON.stringify(await page.evaluate(() => window.__promo.info)));

const save = (file, dataUrl) => fs.writeFileSync(file, Buffer.from(dataUrl.split(',')[1], 'base64'));

if (flag('stills')) {
  const dir = path.join(outDir, 'stills');
  fs.mkdirSync(dir, { recursive: true });
  const stills = await page.evaluate(() => window.__promo.stills);
  for (const s of stills) {
    const png = await page.evaluate(([id, sub]) => window.__promo.renderStill(id, sub), [s.id, subtitles]);
    save(path.join(dir, `${s.id}.png`), png);
    console.log('静帧', s.id, s.label);
  }
} else if (arg('at')) {
  const t = Number(arg('at'));
  const png = await page.evaluate(([t, sub]) => window.__promo.renderFrame(t, sub), [t, subtitles]);
  const f = path.join(outDir, `frame_${t.toFixed(3)}.png`);
  save(f, png);
  console.log('已输出', f);
} else {
  const fps = Number(arg('fps', 30));
  const from = Number(arg('from', 0));
  const to = Number(arg('to', 7));
  const out = path.resolve(arg('out', 'output/opening-7s.mp4'));
  const framesDir = path.resolve(arg('frames-dir', path.join(outDir, 'frames')));
  fs.rmSync(framesDir, { recursive: true, force: true });
  fs.mkdirSync(framesDir, { recursive: true });
  const n = Math.round((to - from) * fps);
  const t0 = Date.now();
  for (let i = 0; i < n; i++) {
    const t = from + i / fps; // 帧时间严格按帧号计算，可复现
    const png = await page.evaluate(([t, sub]) => window.__promo.renderFrame(t, sub), [t, subtitles]);
    save(path.join(framesDir, `${String(i).padStart(5, '0')}.png`), png);
    if (i % 15 === 0) console.log(`帧 ${i + 1}/${n}  t=${t.toFixed(3)}s  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
  const ff = spawnSync(
    'ffmpeg',
    [
      '-y', '-loglevel', 'error',
      '-framerate', String(fps),
      '-i', path.join(framesDir, '%05d.png'),
      '-c:v', 'libx264', '-preset', 'slow', '-crf', '14',
      '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
      '-movflags', '+faststart',
      out,
    ],
    { stdio: 'inherit' },
  );
  if (ff.status !== 0) {
    console.error('ffmpeg 编码失败（请确认已安装 ffmpeg 并在 PATH 中）；PNG 序列保留在', framesDir);
    process.exit(1);
  }
  if (!flag('keep-frames')) fs.rmSync(framesDir, { recursive: true, force: true });
  console.log('已输出', out);
}
await browser.close();
server.close();
