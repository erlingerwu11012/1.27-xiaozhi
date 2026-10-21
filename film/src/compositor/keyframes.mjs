// Compose one storyboard keyframe per shot: background (3D render / Higgsfield plate / black) + overlay graphics.
// node keyframes.mjs  ->  ../../storyboard/keyframes/Sxx.png
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import puppeteer from 'puppeteer-core';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJ = path.resolve(HERE, '..', '..');
const OUT = path.join(PROJ, 'storyboard', 'keyframes');
const TL = JSON.parse(fs.readFileSync(path.join(PROJ, 'src', 'timeline.json'), 'utf8'));
const BOX = JSON.parse(fs.readFileSync(path.join(PROJ, 'build', 'product_screen.json'), 'utf8'));
const BROWSER = process.env.BROWSER_PATH || ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome', '/usr/bin/chromium', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(fs.existsSync);
const url = p => pathToFileURL(p).href;
const R3D = id => url(path.join(PROJ, 'build', 'keyframes-3d', id + '.png'));
const PLATE = n => {
  const a = path.join(PROJ, 'plates', n + '.png');
  return url(fs.existsSync(a) ? a : path.join(PROJ, 'plates', n + '.png'));
};
const WHO = { U: '你', X: '小念', X2: '小念 · 新音色', D: '某智能设备' };

export function stateFor(s) {
  const st = {};
  const box = BOX[s.id];
  const pcx = box ? (box.bbox[0] + box.bbox[2]) / 2 : 560;      // plates: subject sits left of centre
  const textLeft = pcx > 960;
  st.lb = s.letterbox === 1;
  if (s.kind === '3d' || s.kind === '3d+plate') st.bg = R3D(s.id);
  else if (s.kind === 'plate') st.bg = PLATE(s.src);
  else { st.bg = null; st.black = 1; }

  if (s.grade === 'desat') st.black = 0.25;
  if (s.id === 'S02') { st.bg = R3D('S01'); st.black = 0.6; }
  const nar = s.lines.filter(l => l.who === 'N');
  if (nar.length && !s.end_title) st.sub = nar.map(l => l.text).join('');
  const talk = (s.whisper || s.end_title) ? [] : s.lines.filter(l => l.who !== 'N');
  const bx = textLeft ? 150 : 1200;
  let by = s.chapter && textLeft ? 470 : 360;
  if (st.lb) by = Math.max(by, 400);
  st.bubbles = talk.map((l, i) => ({ cls: l.who === 'X' || l.who === 'X2' ? 'x' : l.who === 'D' ? 'd' : 'u', who: WHO[l.who], text: l.text,
    x: bx + (l.who === 'X' || l.who === 'X2' ? 60 : 0), y: by + i * 170 }));
  if (s.chapter) st.chapter = { no: s.chapter[0], name: s.chapter[1], desc: s.chapter[2], side: textLeft ? 'l' : 'r' };
  if (s.tag) st.tag = { text: s.tag, sub: s.tag_sub, x: 1180, y: 250 };
  if (s.tags_all) st.tagsAll = true;
  if (s.big) st.big = s.big;
  if (s.whisper) st.whisper = s.whisper;
  if (s.title_small) st.smallTitle = s.title_small;
  if (s.title) st.title = { sub: s.title_sub };
  if (s.corner) { st.corner = s.corner; st.cornerSide = s.chapter && textLeft ? 'r' : 'l'; }
  if (s.corner_r) st.cornerR = s.corner_r;
  if (s.feature) st.feature = { kicker: '让它成为你的', text: s.feature, side: textLeft ? 'l' : 'r' };
  if (s.card === 'wake') st.wake = { text: '你好，小念', x: textLeft ? 150 : 1240, y: 300 };
  if (s.diagram) st.diagram = true;
  if (s.end_title) { st.end = true; st.black = 0.25; }
  if (s.sense_ring && box) {
    const [x0, , x1, y1] = box.bbox, w = (x1 - x0);
    st.rings = [{ x: box.base[0], y: y1 - 6, w: w * 2.3, h: w * 0.42 }, { x: box.base[0], y: y1 - 6, w: w * 3.4, h: w * 0.62, cls: 'r2' }];
  }
  return st;
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  fs.mkdirSync(OUT, { recursive: true });
  const b = await puppeteer.launch({ executablePath: BROWSER, headless: true, args: ['--allow-file-access-from-files'] });
  const pg = await b.newPage();
  await pg.setViewport({ width: 1920, height: 1080 });
  await pg.goto(url(path.join(HERE, 'overlay.html')));
  await pg.waitForFunction('window.ready');
  const only = process.argv.slice(2);
  for (const s of TL.shots) {
    if (only.length && !only.includes(s.id)) continue;
    await pg.evaluate(st => window.render(st), stateFor(s));
    await pg.evaluate(() => document.fonts.ready);
    await pg.screenshot({ path: path.join(OUT, s.id + '.png') });
    console.log('keyframe', s.id);
  }
  await b.close();
}
