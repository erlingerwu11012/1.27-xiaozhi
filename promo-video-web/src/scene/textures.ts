/** 程序化纹理（固定种子，可复现）：深色胡桃木桌面、墙面灰泥、接触阴影 */
import * as THREE from 'three';
import { seeded } from '../core/math';

function makeNoise(seed: number, size = 256) {
  const rnd = seeded(seed);
  const tab = new Float32Array(size * size).map(() => rnd());
  const at = (x: number, y: number) => tab[((y & (size - 1)) * size + (x & (size - 1))) | 0];
  const smooth = (t: number) => t * t * (3 - 2 * t);
  const value = (x: number, y: number) => {
    const xi = Math.floor(x),
      yi = Math.floor(y);
    const xf = smooth(x - xi),
      yf = smooth(y - yi);
    const a = at(xi, yi),
      b = at(xi + 1, yi),
      c = at(xi, yi + 1),
      d = at(xi + 1, yi + 1);
    return a + (b - a) * xf + (c - a) * yf + (a - b - c + d) * xf * yf;
  };
  const fbm = (x: number, y: number, oct = 4) => {
    let s = 0,
      amp = 0.5,
      f = 1;
    for (let i = 0; i < oct; i++) {
      s += amp * value(x * f, y * f);
      f *= 2;
      amp *= 0.5;
    }
    return s;
  };
  return { value, fbm };
}

/** 深色胡桃木：纹理沿 u 方向 */
export function walnutTextures() {
  const W = 2048,
    H = 1024;
  const n = makeNoise(7);
  const color = document.createElement('canvas');
  color.width = W;
  color.height = H;
  const rough = document.createElement('canvas');
  rough.width = W;
  rough.height = H;
  const cc = color.getContext('2d')!,
    rc = rough.getContext('2d')!;
  const ci = cc.createImageData(W, H),
    ri = rc.createImageData(W, H);
  const dark = [38, 25, 17],
    mid = [62, 42, 29],
    light = [84, 58, 40];
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const u = x / W,
        v = y / H;
      // 长纹理沿 u；低频扭曲让纹路不规则，避免规则条纹
      const warp = n.fbm(u * 2.2, v * 3.5) * 5.5 + n.fbm(u * 0.5 + 10, v * 1.2) * 9;
      const ring = Math.sin((v * 17 + warp) * Math.PI);
      const g = 0.5 + 0.5 * ring;
      const fine = n.value(x * 0.6, y * 0.05) * 0.6 + n.value(x * 0.21, y * 1.4) * 0.4;
      const tone = n.fbm(u * 1.2 + 3, v * 2.5 + 7, 4);
      let t = 0.42 + (g - 0.5) * 0.22 + (tone - 0.5) * 0.7 + (fine - 0.5) * 0.12;
      const pores = fine;
      t = Math.min(1, Math.max(0, t));
      const c = t < 0.5 ? dark.map((d, i) => d + (mid[i] - d) * (t / 0.5)) : mid.map((m, i) => m + (light[i] - m) * ((t - 0.5) / 0.5));
      const o = (y * W + x) * 4;
      ci.data[o] = c[0];
      ci.data[o + 1] = c[1];
      ci.data[o + 2] = c[2];
      ci.data[o + 3] = 255;
      const r = 150 + (1 - g) * 40 + pores * 50;
      ri.data[o] = ri.data[o + 1] = ri.data[o + 2] = Math.min(255, r);
      ri.data[o + 3] = 255;
    }
  }
  cc.putImageData(ci, 0, 0);
  rc.putImageData(ri, 0, 0);
  const map = new THREE.CanvasTexture(color);
  map.colorSpace = THREE.SRGBColorSpace;
  const roughnessMap = new THREE.CanvasTexture(rough);
  for (const t of [map, roughnessMap]) {
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.anisotropy = 8;
  }
  return { map, roughnessMap };
}

/** 墙面：极轻的灰泥起伏，避免大面积暗部出现色带 */
export function plasterTexture() {
  const S = 512;
  const n = makeNoise(21);
  const c = document.createElement('canvas');
  c.width = c.height = S;
  const ctx = c.getContext('2d')!;
  const img = ctx.createImageData(S, S);
  for (let y = 0; y < S; y++)
    for (let x = 0; x < S; x++) {
      const v = 118 + (n.fbm(x / 40, y / 40, 5) - 0.5) * 30 + (n.value(x * 0.7, y * 0.7) - 0.5) * 8;
      const o = (y * S + x) * 4;
      img.data[o] = img.data[o + 1] = img.data[o + 2] = v;
      img.data[o + 3] = 255;
    }
  ctx.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

/**
 * 底座接触阴影：直接用 base 零件三角面投影到桌面得到真实外形轮廓，
 * 再做几层不同半径的模糊叠加。贴图覆盖 EXTENT_X×EXTENT_Z mm，中心在模型原点。
 */
export const CONTACT_EXTENT = { x: 200, z: 150 };
export function contactShadowTexture(base: THREE.BufferGeometry) {
  const S = 512;
  const sil = document.createElement('canvas');
  sil.width = sil.height = S;
  const sctx = sil.getContext('2d')!;
  const pos = base.getAttribute('position');
  const idx = base.getIndex()!;
  const px = (x: number) => (x / CONTACT_EXTENT.x + 0.5) * S;
  const pz = (z: number) => (z / CONTACT_EXTENT.z + 0.5) * S;
  sctx.fillStyle = '#000';
  sctx.beginPath();
  for (let i = 0; i < idx.count; i += 3) {
    const a = idx.getX(i),
      b = idx.getX(i + 1),
      c = idx.getX(i + 2);
    sctx.moveTo(px(pos.getX(a)), pz(pos.getZ(a)));
    sctx.lineTo(px(pos.getX(b)), pz(pos.getZ(b)));
    sctx.lineTo(px(pos.getX(c)), pz(pos.getZ(c)));
    sctx.closePath();
  }
  sctx.fill('nonzero');
  sctx.lineWidth = 1;
  sctx.strokeStyle = '#000';
  sctx.stroke();

  const c = document.createElement('canvas');
  c.width = c.height = S;
  const ctx = c.getContext('2d')!;
  const mm = S / CONTACT_EXTENT.x;
  const layers: [number, number][] = [
    [1.2, 0.9], // 紧贴边缘
    [5, 0.45],
    [14, 0.3],
  ];
  for (const [blur, alpha] of layers) {
    ctx.save();
    ctx.filter = `blur(${blur * mm}px)`;
    ctx.globalAlpha = alpha;
    ctx.drawImage(sil, 0, 0);
    ctx.restore();
  }
  return new THREE.CanvasTexture(c);
}
