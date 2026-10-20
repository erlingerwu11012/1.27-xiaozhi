/**
 * 原 Spine 角色播放器：官方 runtime + 原 nvhai.skel / nvhai.atlas / texture.png，
 * 只播放原 idle（4.2.43，约 5.333s，循环）。
 *
 * 布局参数来自 full-screen.html，并已复核：
 *  - 320×320 世界视口，skeleton 位置 (170.764, 42.510)，渲染到 640×640；
 *  - 身体 / 上臂 / 衣领（shenti, dabir, dabil, yiling）在 room.png 桌沿（画面 y=536/640）以下裁切，
 *    前臂与手（xiaobil, xiaobir）不裁切、搭在桌面上 → 手臂完整，桌沿关系正确；
 *  - 该骨架没有物理约束，idle 是时间的纯函数：每帧 setToSetupPose + trackTime=t 即可精确定位。
 */
export const SPINE_LAYOUT = {
  size: 640,
  viewport: 320,
  position: [170.764, 42.51] as const,
  tableEdgeFromTop: 536, // 640 画布坐标
  rearClippedSlots: ['shenti', 'dabir', 'dabil', 'yiling'],
};

export class SpineIdle {
  readonly canvas: HTMLCanvasElement;
  private gl!: WebGLRenderingContext;
  private renderer!: spine.SceneRenderer;
  private skeleton!: spine.Skeleton;
  private state!: spine.AnimationState;
  private entry!: spine.TrackEntry;
  version = '';
  idleDuration = 0;

  constructor() {
    this.canvas = document.createElement('canvas');
    this.canvas.width = this.canvas.height = SPINE_LAYOUT.size;
  }

  async load(base: string) {
    if (typeof spine === 'undefined') throw new Error('Spine runtime 未加载（public/vendor/spine-webgl.js）');
    const gl = this.canvas.getContext('webgl', {
      alpha: true,
      premultipliedAlpha: true,
      preserveDrawingBuffer: true,
    });
    if (!gl) throw new Error('无法创建 Spine WebGL 上下文');
    this.gl = gl;
    this.renderer = new spine.SceneRenderer(this.canvas, gl);
    const am = new spine.AssetManager(gl, base);
    am.loadBinary('nvhai.skel');
    am.loadTextureAtlas('nvhai.atlas');
    while (!am.isLoadingComplete()) await new Promise((r) => setTimeout(r, 16));
    if (am.hasErrors()) throw new Error('Spine 资源加载失败：' + JSON.stringify(am.getErrors()));
    const data = new spine.SkeletonBinary(new spine.AtlasAttachmentLoader(am.require('nvhai.atlas'))).readSkeletonData(
      am.require('nvhai.skel'),
    );
    this.version = data.version;
    const idle = data.animations.find((a) => a.name === 'idle');
    if (!idle) throw new Error('nvhai.skel 中没有 idle 动画');
    this.idleDuration = idle.duration;
    this.skeleton = new spine.Skeleton(data);
    this.skeleton.setSkinByName('default');
    this.skeleton.setToSetupPose();
    this.skeleton.x = SPINE_LAYOUT.position[0];
    this.skeleton.y = SPINE_LAYOUT.position[1];
    const half = SPINE_LAYOUT.viewport / 2;
    this.renderer.camera.position.x = half;
    this.renderer.camera.position.y = half;
    this.renderer.camera.viewportWidth = SPINE_LAYOUT.viewport;
    this.renderer.camera.viewportHeight = SPINE_LAYOUT.viewport;
    this.renderer.camera.update();
    this.state = new spine.AnimationState(new spine.AnimationStateData(data));
    this.entry = this.state.setAnimation(0, 'idle', true);
  }

  /** 绘制 idle 第 time 秒（循环），结果在 this.canvas（预乘 alpha，透明背景） */
  drawAt(time: number) {
    const { gl, skeleton, renderer } = this;
    skeleton.setToSetupPose();
    this.entry.trackTime = Math.max(0, time);
    this.state.apply(skeleton);
    skeleton.updateWorldTransform(spine.Physics.update);

    const S = SPINE_LAYOUT.size;
    gl.viewport(0, 0, S, S);
    gl.disable(gl.SCISSOR_TEST);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    const clipFromBottom = S - SPINE_LAYOUT.tableEdgeFromTop; // GL 坐标原点在左下
    for (const slot of skeleton.drawOrder) {
      if (SPINE_LAYOUT.rearClippedSlots.includes(slot.data.name)) {
        gl.enable(gl.SCISSOR_TEST);
        gl.scissor(0, clipFromBottom, S, S - clipFromBottom);
      } else gl.disable(gl.SCISSOR_TEST);
      renderer.begin();
      renderer.drawSkeleton(skeleton, false, slot.data.index, slot.data.index);
      renderer.end();
    }
    gl.disable(gl.SCISSOR_TEST);
  }
}
