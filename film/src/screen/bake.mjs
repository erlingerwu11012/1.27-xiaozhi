// Bake LCD content frames with headless Edge + official Spine runtime.
// node bake.mjs [idleSeconds=16] [fps=30]
// -> ../../build/screen/idle/0000.png..., ../../build/screen/boot/000.png...
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import puppeteer from 'puppeteer-core';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJ = path.resolve(HERE, '..', '..');            // promo-video-v2-20261018
const OUTPUTS = PROJ;                // outputs/
const OUT = path.join(PROJ, 'build', 'screen');
const idleSec = +(process.argv[2] || 16), fps = +(process.argv[3] || 30);
const BROWSER = process.env.BROWSER_PATH || ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome', '/usr/bin/chromium', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(fs.existsSync);

const types = { '.html': 'text/html', '.js': 'text/javascript', '.png': 'image/png', '.atlas': 'text/plain', '.skel': 'application/octet-stream' };
const srv = http.createServer((req, res) => {
  const u = decodeURIComponent(req.url.split('?')[0]);
  const f = u.startsWith('/__screen/') ? path.join(HERE, u.slice(10)) : path.join(OUTPUTS, u);
  fs.readFile(f, (e, b) => { if (e) { res.writeHead(404); res.end(); return; } res.writeHead(200, { 'Content-Type': types[path.extname(f)] || 'application/octet-stream' }); res.end(b); });
}).listen(8823, '127.0.0.1');

const save = (dir, name, url) => fs.writeFileSync(path.join(dir, name), Buffer.from(url.split(',')[1], 'base64'));
try {
  const b = await puppeteer.launch({ executablePath: BROWSER, headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const pg = await b.newPage();
  pg.on('console', m => ['error', 'warn'].includes(m.type()) && console.log('console:', m.text()));
  await pg.goto('http://127.0.0.1:8823/__screen/screen.html');
  await pg.waitForFunction('window.ready || window.err', { timeout: 120000 });
  const err = await pg.evaluate('window.err'); if (err) throw Error(err);
  console.log('spine', await pg.evaluate('window.spineVersion'));
  for (const d of ['idle', 'boot']) fs.mkdirSync(path.join(OUT, d), { recursive: true });
  const nb = Math.round(2.5 * fps);
  for (let i = 0; i < nb; i++) save(path.join(OUT, 'boot'), String(i).padStart(3, '0') + '.png', await pg.evaluate(t => drawBoot(t), i / fps));
  const n = Math.round(idleSec * fps);
  for (let i = 0; i < n; i++) {
    if (i) await pg.evaluate(dt => advance(dt), 1 / fps);
    save(path.join(OUT, 'idle'), String(i).padStart(4, '0') + '.png', await pg.evaluate(() => drawIdle()));
    if (i % 60 === 0) console.log('idle', i, '/', n);
  }
  await b.close();
  console.log('done', OUT);
} finally { srv.close(); }
