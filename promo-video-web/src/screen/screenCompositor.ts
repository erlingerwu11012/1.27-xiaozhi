/**
 * 屏幕内容合成：整块屏幕始终是同一张 640×640 画布（→ Three.js CanvasTexture），
 * 再整体映射到 LCD 有效区。黑屏 / 原开机帧 / 原 room.png + 原 Spine idle 都在这里切换，
 * 壁纸与角色同在一张纹理上，位置不会彼此漂移。
 */
import type { ScreenState } from '../core/timeline';
import { BOOT } from '../core/timeline';
import { SpineIdle, SPINE_LAYOUT } from './spineIdle';

function loadImage(src: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const im = new Image();
    im.onload = () => resolve(im);
    im.onerror = () => reject(new Error('图片加载失败 ' + src));
    im.src = src;
  });
}

export class ScreenCompositor {
  readonly canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private layer: HTMLCanvasElement;
  private layerCtx: CanvasRenderingContext2D;
  private boot: HTMLImageElement[] = [];
  private room!: HTMLImageElement;
  readonly spine = new SpineIdle();
  /** 每次内容变化 +1，供纹理判断是否需要上传 */
  version = 0;
  private lastKey = '';

  constructor() {
    this.canvas = document.createElement('canvas');
    this.canvas.width = this.canvas.height = SPINE_LAYOUT.size;
    this.ctx = this.canvas.getContext('2d')!;
    this.layer = document.createElement('canvas');
    this.layer.width = this.layer.height = SPINE_LAYOUT.size;
    this.layerCtx = this.layer.getContext('2d')!;
  }

  async load(assetBase: string) {
    const frames = Array.from({ length: BOOT.frames }, (_, i) =>
      loadImage(`${assetBase}boot/${String(i).padStart(3, '0')}.png`),
    );
    const [room, ...boot] = await Promise.all([loadImage(`${assetBase}spine/room.png`), ...frames]);
    this.room = room;
    this.boot = boot;
    await this.spine.load(`${assetBase}spine/`);
  }

  draw(s: ScreenState) {
    const key =
      s.kind === 'black' ? 'black' : s.kind === 'boot' ? `boot${s.frame}` : `idle${s.idleTime.toFixed(5)}_${s.brightness}`;
    if (key === this.lastKey) return;
    this.lastKey = key;
    this.version++;
    const { ctx } = this;
    const S = SPINE_LAYOUT.size;
    ctx.globalAlpha = 1;
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, S, S);
    if (s.kind === 'boot') {
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(this.boot[s.frame], 0, 0, S, S);
    } else if (s.kind === 'idle') {
      // 先把壁纸 + 角色合成为一层，再整体调亮度：二者同时亮起、相对位置恒定
      this.spine.drawAt(s.idleTime);
      const l = this.layerCtx;
      l.imageSmoothingEnabled = true;
      l.imageSmoothingQuality = 'high';
      l.clearRect(0, 0, S, S);
      l.drawImage(this.room, 0, 0, S, S);
      l.drawImage(this.spine.canvas, 0, 0);
      ctx.globalAlpha = s.brightness;
      ctx.drawImage(this.layer, 0, 0);
      ctx.globalAlpha = 1;
    }
  }
}
