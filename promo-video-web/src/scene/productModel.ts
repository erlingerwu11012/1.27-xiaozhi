/**
 * parts-data.json 加载器。
 * 字段已实测：数组，8 个零件，每个包含
 *   name, positions(base64 Float32 xyz), normals(base64 Float32 xyz),
 *   indices(base64 Uint32), bounds{min,max,size,vertices,triangles,...}
 * 单位 mm，Y 轴向上，+Z 为屏幕正面。8 个零件共用装配坐标：
 * 这里对任何零件都不做平移 / 旋转 / 缩放，只把整机作为一个整体放到桌面上。
 */
import * as THREE from 'three';

export const PART_NAMES = [
  'base',
  'buttons',
  'front',
  'left_knob',
  'left_support',
  'rear',
  'right_knob',
  'right_support',
] as const;
export type PartName = (typeof PART_NAMES)[number];

interface RawBounds {
  min: [number, number, number];
  max: [number, number, number];
  vertices: number;
  triangles: number;
}
interface RawPart {
  name: string;
  positions: string;
  normals: string;
  indices: string;
  bounds: RawBounds;
}

function b64(s: string): ArrayBuffer {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

export async function loadParts(url: string): Promise<Map<PartName, THREE.BufferGeometry>> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`无法加载模型 ${url}: ${res.status}`);
  const raw = (await res.json()) as RawPart[];
  const out = new Map<PartName, THREE.BufferGeometry>();
  for (const p of raw) {
    if (!(PART_NAMES as readonly string[]).includes(p.name)) throw new Error(`未知零件 ${p.name}`);
    const pos = new Float32Array(b64(p.positions));
    const nor = new Float32Array(b64(p.normals));
    const idx = new Uint32Array(b64(p.indices));
    const { vertices, triangles } = p.bounds;
    if (pos.length !== vertices * 3 || nor.length !== vertices * 3 || idx.length !== triangles * 3) {
      throw new Error(`零件 ${p.name} 字段长度与 bounds 不一致`);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    g.computeBoundingBox();
    const bb = g.boundingBox!;
    const err = Math.max(
      ...[0, 1, 2].map((i) => Math.abs(bb.min.getComponent(i) - p.bounds.min[i])),
      ...[0, 1, 2].map((i) => Math.abs(bb.max.getComponent(i) - p.bounds.max[i])),
    );
    if (err > 0.01) throw new Error(`零件 ${p.name} 包围盒与附件不符（误差 ${err.toFixed(3)}mm）`);
    out.set(p.name as PartName, g);
  }
  for (const n of PART_NAMES) if (!out.has(n)) throw new Error(`缺少零件 ${n}`);
  return out;
}

/** 屏幕总成尺寸（dimensions.json → screen_insert），单位 mm，均为模型坐标 */
export const SCREEN_SPEC = {
  coverGlass: [84, 84] as const, // 盖板，坐于前壳 84×84 凹槽（z=14 台阶）
  coverCenter: [0, 0] as const,
  window: [71.64, 70.32] as const, // 盖板丝印开窗 CG-VA
  lcdActive: [71.14, 69.82] as const, // LCD 有效显示区
  lcdOffset: [0, 1.0] as const, // 有效区相对盖板中心偏移（下边黑边更厚）
  zPanel: 14.05,
  zLcd: 14.11, // dimensions.json: display face z=14.11
  zInk: 14.3, // 盖板背面丝印（玻璃厚约 0.6mm）
  zGlass: 14.92, // 盖板外表面，略低于前框面 z=15
};
