/**
 * 渲染引擎：给定时间 t → 输出一帧 1920×1080 成片（frameCanvas）。
 * 预览、截图、无头导出都走这一个函数，所以固定时间的画面可复现。
 */
import { Stage } from '../scene/stage';
import { ScreenCompositor } from '../screen/screenCompositor';
import { drawDialogue, FONT_STACK } from '../overlay/overlay';
import type { StillSpec } from './timeline';
import { cameraAt, HEIGHT, OPENING_DIALOGUE, screenAt, STILLS, WIDTH } from './timeline';

export interface RenderOptions {
  subtitles: boolean;
}

export class Engine {
  readonly frameCanvas: HTMLCanvasElement;
  private frameCtx: CanvasRenderingContext2D;
  private glCanvas: HTMLCanvasElement;
  readonly stage: Stage;
  readonly screen = new ScreenCompositor();
  info: Record<string, unknown> = {};

  constructor() {
    this.glCanvas = document.createElement('canvas');
    this.glCanvas.width = WIDTH;
    this.glCanvas.height = HEIGHT;
    this.frameCanvas = document.createElement('canvas');
    this.frameCanvas.width = WIDTH;
    this.frameCanvas.height = HEIGHT;
    this.frameCtx = this.frameCanvas.getContext('2d')!;
    this.stage = new Stage(this.glCanvas);
  }

  async init(assetBase = './assets/') {
    await Promise.all([
      this.screen.load(assetBase),
      document.fonts.load(`400 40px ${FONT_STACK}`, '今天有点累'),
      document.fonts.load(`500 22px ${FONT_STACK}`, '你它'),
    ]);
    await this.stage.init(assetBase, this.screen);
    this.info = {
      spineVersion: this.screen.spine.version,
      idleDuration: this.screen.spine.idleDuration,
    };
  }

  /** 时间轴上的一帧 */
  renderAt(t: number, opts: RenderOptions) {
    this.screen.draw(screenAt(t));
    this.stage.setCamera(cameraAt(t));
    this.stage.render();
    this.compose(opts.subtitles ? OPENING_DIALOGUE : [], t);
  }

  /** 关键静帧（含草稿机位） */
  renderStill(spec: StillSpec, opts: RenderOptions) {
    if (spec.t !== undefined) return this.renderAt(spec.t, opts);
    this.screen.draw(spec.screen ?? { kind: 'black' });
    this.stage.setCamera(spec.camera ?? cameraAt(0));
    this.stage.render();
    this.compose(opts.subtitles && spec.dialogue ? spec.dialogue.lines : [], spec.dialogue?.at ?? 0);
  }

  stillById(id: string) {
    const s = STILLS.find((x) => x.id === id);
    if (!s) throw new Error('未知静帧 ' + id);
    return s;
  }

  private compose(lines: Parameters<typeof drawDialogue>[2], t: number) {
    const ctx = this.frameCtx;
    ctx.drawImage(this.glCanvas, 0, 0);
    if (lines.length) {
      const snapshot = document.createElement('canvas');
      snapshot.width = WIDTH;
      snapshot.height = HEIGHT;
      snapshot.getContext('2d')!.drawImage(this.glCanvas, 0, 0);
      drawDialogue(ctx, snapshot, lines, t);
    }
  }
}
