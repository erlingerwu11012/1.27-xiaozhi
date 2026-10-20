/**
 * 统一时间轴：镜头、屏幕、字幕、声音都只由时间 t（秒）决定。
 * 任何画面 = render(t)，没有累积状态，因此固定时间截图可完全复现。
 */
import type { Vec3 } from './math';
import { clamp01, easeInOutCubic, lerp, lerpVec3 } from './math';

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

/** 阶段一只交付 0–7 秒开场 */
export const OPENING_DURATION = 7;

// ───────────────────────── 屏幕 ─────────────────────────
export const BOOT = {
  start: 3.0,
  /** 原始 80 帧 / 20fps = 4s，整体 1.6 倍速 → 2.5s，帧不丢不截断 */
  frames: 80,
  sourceFps: 20,
  speed: 1.6,
} as const;
export const BOOT_END = BOOT.start + BOOT.frames / BOOT.sourceFps / BOOT.speed; // 5.5
/** 壁纸与角色作为同一张纹理一起亮起的时长（亮度渐变，不改变位置） */
export const IDLE_LIGHT_UP = 0.2;

export type ScreenState =
  | { kind: 'black' }
  | { kind: 'boot'; frame: number }
  | { kind: 'idle'; idleTime: number; brightness: number };

export function screenAt(t: number): ScreenState {
  if (t < BOOT.start) return { kind: 'black' };
  if (t < BOOT_END) {
    const f = Math.floor((t - BOOT.start) * BOOT.sourceFps * BOOT.speed + 1e-6);
    return { kind: 'boot', frame: Math.min(BOOT.frames - 1, Math.max(0, f)) };
  }
  const idleTime = t - BOOT_END;
  return { kind: 'idle', idleTime, brightness: clamp01(idleTime / IDLE_LIGHT_UP) };
}

// ───────────────────────── 镜头 ─────────────────────────
/**
 * 机位用“围绕产品的球坐标”描述，单位 mm，世界坐标原点在底座底面中心：
 * yaw   ：水平偏角（°），正值 = 机位在产品右前方（可见右侧 BOOT/RST 面）
 * pitch ：俯角（°）
 * dist  ：到注视点距离（mm）
 * target：注视点（世界坐标 mm）
 * fov   ：垂直视场角（°），全程固定，不变焦
 */
export interface CameraPose {
  yaw: number;
  pitch: number;
  dist: number;
  target: Vec3;
  fov: number;
  /** 景深对焦距离（mm），默认 = dist */
  focus?: number;
}

export const LENS_FOV = 26; // ≈ 全画幅 50mm 垂直视场

/** 屏幕中心在世界坐标中的位置（模型 y 平移 +67） */
export const SCREEN_CENTER_WORLD: Vec3 = [0, 68, 14.5];
export const PRODUCT_CENTER_WORLD: Vec3 = [0, 59.5, 3];

const OPENING_FROM: CameraPose = {
  yaw: 34,
  pitch: 7.5,
  dist: 930,
  target: [0, 62, 3],
  fov: LENS_FOV,
};
const OPENING_TO: CameraPose = {
  yaw: 25,
  pitch: 6.5,
  dist: 395,
  target: [0, 64.5, 8],
  fov: LENS_FOV,
};

/** 0–7 秒：一次连续、匀缓的推镜（单一缓动曲线，无抖动、无变焦） */
export function cameraAt(t: number): CameraPose {
  const k = easeInOutCubic(clamp01(t / OPENING_DURATION));
  // 推进距离在对数空间插值，视觉上的推进速度更均匀
  const dist = Math.exp(lerp(Math.log(OPENING_FROM.dist), Math.log(OPENING_TO.dist), k));
  return {
    yaw: lerp(OPENING_FROM.yaw, OPENING_TO.yaw, k),
    pitch: lerp(OPENING_FROM.pitch, OPENING_TO.pitch, k),
    dist,
    target: lerpVec3(OPENING_FROM.target, OPENING_TO.target, k),
    fov: LENS_FOV,
  };
}

// ─────────────────────── 字幕 / 对话框 ───────────────────────
export type Speaker = 'user' | 'device';
export interface DialogueLine {
  speaker: Speaker;
  text: string;
  /** 出现时间（秒，相对所在镜头） */
  in: number;
  /** 可选的小标签，如“此前”“几天后” */
  tag?: string;
}

/** 开场 0–7 秒：不配音、不加音乐、不加文字 */
export const OPENING_DIALOGUE: DialogueLine[] = [];

// ───────────────────────── 声音 ─────────────────────────
/**
 * 可替换音轨接口：每条音轨 = 一个音频文件 + 起点。
 * 开场阶段按要求为空；完整版的画外音 / 音效 / 配乐在此登记即可，与画面共用时间轴。
 */
export interface AudioCue {
  id: string;
  src: string; // 相对 public/ 的路径
  start: number; // 秒
  gain: number; // 0–1
  kind: 'voice' | 'sfx' | 'music';
}
export const OPENING_AUDIO: AudioCue[] = [];

// ───────────────────────── 静帧 ─────────────────────────
export interface StillSpec {
  id: string;
  label: string;
  /** 若给出 t，则完全按时间轴渲染 */
  t?: number;
  /** 草稿静帧（非开场时间轴）：直接指定镜头 / 屏幕 / 对话 */
  camera?: CameraPose;
  screen?: ScreenState;
  dialogue?: { lines: DialogueLine[]; at: number };
}

/** “对话功能画面”草稿机位：产品在左三分线，右侧留给对话框 */
export const DIALOGUE_DRAFT_CAMERA: CameraPose = {
  yaw: 22,
  pitch: 6,
  dist: 470,
  target: [92, 63, 8],
  fov: LENS_FOV,
  focus: 470,
};

export const STILLS: StillSpec[] = [
  { id: '01-opening-wide', label: '开场远景（0.0s）', t: 0.0 },
  { id: '02-screen-on-close', label: '亮屏近景（6.6s）', t: 6.6 },
  {
    id: '03-dialogue-draft',
    label: '对话功能画面（草稿，对应 14–21s 段）',
    camera: DIALOGUE_DRAFT_CAMERA,
    screen: { kind: 'idle', idleTime: 2.4, brightness: 1 },
    dialogue: {
      at: 10,
      lines: [
        { speaker: 'user', text: '今天有点累。', in: 0 },
        { speaker: 'device', text: '那就先歇一会儿，想跟我聊聊吗？', in: 1.6 },
      ],
    },
  },
];
