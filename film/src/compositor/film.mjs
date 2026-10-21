// Frame compositor for the whole film. Background (3D sequence / plate with slow move / black) + animated overlay,
// everything driven by timeline.json. Used for the proxy preview and, at full size, for the final.
//   node film.mjs --scale 0.3333 --step 3 --src build/proxy3d --out build/proxy_frames
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import puppeteer from 'puppeteer-core';
import { stateFor } from './keyframes.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJ = path.resolve(HERE, '..', '..');
const TL = JSON.parse(fs.readFileSync(path.join(PROJ, 'src', 'timeline.json'), 'utf8'));
const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };
const SCALE = +arg('scale', 1), STEP = +arg('step', 1);
const SRC3D = path.resolve(PROJ, arg('src', 'build/final3d'));
const OUT = path.resolve(PROJ, arg('out', 'build/final_frames'));
const ONLY = (arg('shots', '') || '').split(',').filter(Boolean);
const BROWSER = process.env.BROWSER_PATH || ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Google/Chrome/Application/chrome.exe', '/usr/bin/google-chrome', '/usr/bin/chromium', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(fs.existsSync);
const url = p => pathToFileURL(p).href;
const PLATE = n => { const a = path.join(PROJ, 'plates', n + '.png'); return url(fs.existsSync(a) ? a : path.join(PROJ, 'plates', n + '.png')); };
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const ease = x => { x = clamp(x); return x * x * (3 - 2 * x); };
const fadeIn = (t, t0, d = 0.3) => ease((t - t0) / d);

function frame3d(id, i) {
  const d = path.join(SRC3D, id);
  for (let k = i; k >= 0; k--) { const f = path.join(d, String(k).padStart(4, '0') + '.png'); if (fs.existsSync(f)) return url(f); }
  return null;
}

// plate camera moves: [scale0, scale1, x0, x1, y0, y1] in % of frame
const MOVES = { S03: [1.04, 1.10, 0, -1, 0, 0], S04a: [1.06, 1.10, 1, 0, 0, 0], S04b: [1.16, 1.24, -1, -1, 0, 0], S04c: [1.10, 1.14, 0, 1, 0, 0],
  S05: [1.02, 1.07, 0, 0, 0, 0], S06: [1.16, 1.0, 0, 0, -1, 0], S11: [1.03, 1.08, 0, -1, 0, 0], S15: [1.02, 1.05, 0, 0, 0, 0] };

function stateAt(s, t) {                      // t = seconds into the shot
  const T = s.end - s.start, u = t / T;
  const st = stateFor(s);                     // static layout (positions, texts) from the keyframe composer
  const abs = s.start + t;
  if (s.kind === '3d' || s.kind === '3d+plate') st.bg = frame3d(s.id, Math.round(t * 30));
  if (s.id === 'S02') { const n = TL.shots[0].frames; st.bg = frame3d('S01', n - 1); st.black = 0.35 + 0.35 * u; }
  const mv = MOVES[s.id];
  if (mv && s.kind === 'plate') st.bgMove = { s: mv[0] + (mv[1] - mv[0]) * ease(u), x: mv[2] + (mv[3] - mv[2]) * u, y: mv[4] + (mv[5] - mv[4]) * u };
  if (s.kind === '3d+plate') {        // desk lamp dims in 3D, then cut to the living room: lights off + curtains
    const l = s.lines[0], cut = l.start + 2.3;
    if (abs >= cut) {
      st.bg = PLATE(s.src + '-on'); st.bgB = PLATE(s.src + '-off'); st.bgBk = fadeIn(abs, cut + 0.4, 1.0);
      st.bgMove = { s: 1.02 + 0.03 * ease((abs - cut) / (s.end - cut)), x: 0, y: 0 };
    }
  }
  // letterbox
  if (s.id === 'S02') st.lb = true, st.lbh = 138 * ease(u * 1.4);
  if (s.letterbox === 'open') { st.lb = true; st.lbh = 138 * (1 - ease((u - 0.3) / 0.4)); }
  // fades
  if (s.id === 'S01') st.black = 1 - fadeIn(t, 0, 1.0);
  if (s.id === 'S22') st.black = Math.max(st.black ?? 0, 0.25 * fadeIn(t, 1.8, 1.2)) + 0.75 * fadeIn(t, T - 1.0, 1.0);
  // narrator subtitle: only while the line plays
  const nar = s.lines.filter(l => l.who === 'N' && abs >= l.start - 0.1 && abs <= l.end + 0.35);
  st.sub = s.end_title ? null : (nar.length ? nar.map(l => l.text).join('') : null);
  if (s.end_title && abs < s.lines[1].start) st.sub = null;
  // dialog bubbles appear on their line
  const talk = (st.bubbles || []);
  const tl = s.lines.filter(l => l.who !== 'N');
  talk.forEach((b, i) => { const l = tl[i]; b.o = fadeIn(abs, l.start - 0.15, 0.25); b.y += 14 * (1 - b.o); });
  st.bubbles = talk.filter(b => b.o > 0.01);
  if (st.chapter) st.chapterO = fadeIn(t, 0.25, 0.5);
  if (st.tag) st.tagO = fadeIn(t, 0.1, 0.2);
  if (st.tagsAll) st.tagsAllO = fadeIn(t, 0.4, 0.5);
  if (st.big) st.bigO = fadeIn(t, T - 2.0, 0.6);
  if (st.whisper) st.whisperO = fadeIn(abs, s.lines[0].start - 0.2, 0.6) * (1 - fadeIn(t, T - 0.4, 0.4));
  if (st.smallTitle) st.smallTitleO = fadeIn(t, 0.2, 0.4) * (1 - fadeIn(t, T - 0.4, 0.4));
  if (st.title) st.titleO = fadeIn(t, 0.4, 0.8);
  if (st.corner) st.cornerO = fadeIn(t, 0.2, 0.3);
  if (st.feature) st.featureO = fadeIn(t, 0.3, 0.4);
  if (st.wake) {                       // type the default name, then rename, then back
    const full = '你好，小念', alt = '嘿，团子';
    const a = clamp((t - 0.3) / 0.8), b = clamp((t - 1.8) / 0.6), c = clamp((t - 2.8) / 0.6);
    let txt = full.slice(0, Math.ceil(a * full.length));
    if (b > 0) txt = c > 0 ? full.slice(0, Math.ceil(c * full.length)) : alt.slice(0, Math.ceil(b * alt.length));
    st.wake.text = txt; st.wakeO = fadeIn(t, 0.1, 0.3);
  }
  if (st.diagram) st.diagramStep = clamp(Math.floor((t - 0.4) / 0.9), -1, 4);
  if (st.end) st.endStep = [fadeIn(t, 0.3, 0.8), fadeIn(t, 1.6, 0.6), fadeIn(t, 2.2, 0.6), fadeIn(t, 2.8, 0.6)];
  if (st.rings) { const p = (t * 0.45) % 1; st.rings = st.rings.map((r, i) => ({ ...r, w: r.w * (0.7 + 0.5 * ((p + i * 0.5) % 1)), h: r.h * (0.7 + 0.5 * ((p + i * 0.5) % 1)), o: (1 - ((p + i * 0.5) % 1)) * fadeIn(t, 0.3, 0.6) })); }
  if (s.id === 'S07') { st.bg = null; st.black = 1; }
  return st;
}

const b = await puppeteer.launch({ executablePath: BROWSER, headless: true, args: ['--allow-file-access-from-files'] });
const pg = await b.newPage();
await pg.setViewport({ width: 1920, height: 1080, deviceScaleFactor: SCALE });
await pg.goto(url(path.join(HERE, 'overlay.html')));
await pg.waitForFunction('window.ready');
fs.mkdirSync(OUT, { recursive: true });
let n = 0; const t0 = Date.now();
for (const s of TL.shots) {
  if (ONLY.length && !ONLY.includes(s.id)) continue;
  for (let f = s.start_f; f < s.end_f; f += 1) {
    if ((f % STEP) !== 0) continue;
    const st = stateAt(s, (f - s.start_f) / 30);
    await pg.evaluate(x => window.render(x), st);
    await pg.screenshot({ path: path.join(OUT, String(f).padStart(5, '0') + '.jpg'), type: 'jpeg', quality: 90 });
    n++;
  }
  console.log('shot', s.id, n, ((Date.now() - t0) / 1000).toFixed(0) + 's');
}
await b.close();
