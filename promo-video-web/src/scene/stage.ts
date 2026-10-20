/**
 * Three.js 场景：深色桌搭 + 原 CAD 产品 + 屏幕总成 + 灯光 + 镜头 + 后期（景深 / 暗角 / 色调映射）。
 * 单位全程 mm；世界原点 = 底座底面中心，桌面 y=0。
 */
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { SMAAPass } from 'three/examples/jsm/postprocessing/SMAAPass.js';
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js';
import type { CameraPose } from '../core/timeline';
import { HEIGHT, WIDTH } from '../core/timeline';
import { loadParts, SCREEN_SPEC, type PartName } from './productModel';
import { contactShadowTexture, CONTACT_EXTENT, plasterTexture, walnutTextures } from './textures';
import type { ScreenCompositor } from '../screen/screenCompositor';
import { DofPass } from './dofPass';

/** 整机放到桌面：只做整体平移（底座底面 y=-67 → 0），不缩放、不旋转、不逐件处理 */
const ASSEMBLY_OFFSET = new THREE.Vector3(0, 67, 0);

const VignetteShader = {
  uniforms: { tDiffuse: { value: null }, strength: { value: 0.32 }, aspect: { value: WIDTH / HEIGHT } },
  vertexShader: /* glsl */ `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse; uniform float strength; uniform float aspect; varying vec2 vUv;
    void main(){
      vec4 c = texture2D(tDiffuse, vUv);
      vec2 d = vUv - 0.5; d.x *= aspect * 0.82;
      float v = smoothstep(1.05, 0.28, length(d));
      gl_FragColor = vec4(c.rgb * mix(1.0 - strength, 1.0, v), c.a);
    }`,
};

export class Stage {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(26, WIDTH / HEIGHT, 60, 9000);
  private composer!: EffectComposer;
  private dof!: DofPass;
  private screenTex!: THREE.CanvasTexture;
  private glassEnv!: THREE.Texture;
  private screenVersion = -1;
  private compositor!: ScreenCompositor;
  readonly product = new THREE.Group();

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: false, // 抗锯齿由 SMAA 后处理负责
      preserveDrawingBuffer: true,
      powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(1);
    this.renderer.setSize(WIDTH, HEIGHT, false);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.NeutralToneMapping; // 保留屏幕原画色彩，避免过曝
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap; // 配合 shadow.radius 得到柔和半影
    this.renderer.shadowMap.autoUpdate = true;
  }

  async init(assetBase: string, compositor: ScreenCompositor) {
    this.compositor = compositor;
    const parts = await loadParts(`${assetBase}models/parts-data.json`);
    this.buildEnvironment();
    this.buildRoom();
    this.buildProduct(parts);
    this.buildLights();
    this.buildComposer();
  }

  // ───────────── 反射环境（玻璃、树脂高光用）：暗房间 + 柔光箱 + 暖色台灯 ─────────────
  private buildEnvironment() {
    const env = new THREE.Scene();
    const room = new THREE.Mesh(
      new THREE.BoxGeometry(10, 10, 10),
      new THREE.MeshBasicMaterial({ color: 0x0d0b0a, side: THREE.BackSide }),
    );
    env.add(room);
    const panel = (w: number, h: number, color: number, intensity: number, pos: THREE.Vector3Tuple) => {
      const m = new THREE.Mesh(
        new THREE.PlaneGeometry(w, h),
        new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(intensity), side: THREE.DoubleSide }),
      );
      m.position.set(...pos);
      m.lookAt(0, 0, 0);
      env.add(m);
    };
    panel(3.2, 2.2, 0xfff2e2, 2.2, [-2.6, 3.0, 3.4]); // 左前上方主光柔光箱
    panel(1.0, 3.0, 0xc9d6ff, 0.9, [3.8, 1.6, -3.0]); // 右后冷色轮廓
    panel(0.7, 0.7, 0xffb066, 2.0, [-4.6, 1.0, -2.0]); // 画外暖色台灯
    panel(2.4, 1.3, 0xf4efe8, 0.55, [-3.2, 0.2, 4.6]); // 左前方大面积柔光：在玻璃上形成克制的反射渐变
    panel(10, 2, 0x2a2018, 0.6, [0, -4.9, 0]); // 桌面暖色反弹
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(env, 0.02).texture;
    this.glassEnv = pmrem.fromScene(this.buildGlassReflectionScene(), 0.01).texture;
    this.scene.environmentIntensity = 0.55;
    pmrem.dispose();
  }

  /**
   * 屏幕玻璃专用反射环境：左前方一块带柔边的大柔光箱 + 画外暖灯的微弱暖色。
   * 推镜时反射随视角自然平移，黑屏时也能读出玻璃质感；与产品照明解耦，不会抬亮树脂。
   */
  private buildGlassReflectionScene() {
    // 用方向函数直接定义反射环境（方位角 az、仰角 el，单位度；az 以 +Z 为 0，向 -X 为负）
    // 开场 0–3s 镜头方位从 34° 推到约 31°，玻璃反射方向随之从 az≈-34° 移到 -31°，
    // 柔光箱右缘放在 -32.5°：黑屏阶段一道柔和的反光缓慢滑过玻璃，亮屏后反射退出、黑边保持深黑。
    const env = new THREE.Scene();
    const mat = new THREE.ShaderMaterial({
      side: THREE.BackSide,
      vertexShader: /* glsl */ `varying vec3 vDir; void main(){ vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
      fragmentShader: /* glsl */ `
        varying vec3 vDir;
        void main(){
          vec3 d = normalize(vDir);
          float az = degrees(atan(d.x, d.z));
          float el = degrees(asin(clamp(d.y, -1.0, 1.0)));
          float box = smoothstep(-62.0, -52.0, az) * (1.0 - smoothstep(-35.5, -30.0, az))
                    * smoothstep(-28.0, -16.0, el) * (1.0 - smoothstep(18.0, 30.0, el));
          float lamp = exp(-pow((az + 82.0) / 7.0, 2.0) - pow((el - 6.0) / 9.0, 2.0));
          vec3 col = vec3(0.004) + vec3(1.0, 0.97, 0.93) * 1.25 * box + vec3(1.0, 0.62, 0.32) * 0.5 * lamp;
          gl_FragColor = vec4(col, 1.0);
        }`,
    });
    env.add(new THREE.Mesh(new THREE.SphereGeometry(5, 64, 32), mat));
    return env;
  }

  // ───────────── 桌面与陈设 ─────────────
  private buildRoom() {
    const { map, roughnessMap } = walnutTextures();
    map.repeat.set(2.2, 1.4);
    roughnessMap.repeat.copy(map.repeat);
    const desk = new THREE.Mesh(
      new THREE.PlaneGeometry(4200, 1900),
      new THREE.MeshPhysicalMaterial({
        map,
        roughnessMap,
        roughness: 0.62,
        clearcoat: 0.35,
        clearcoatRoughness: 0.32,
        dithering: true,
      }),
    );
    desk.rotation.x = -Math.PI / 2;
    desk.position.set(0, 0, -250);
    desk.receiveShadow = true;
    this.scene.add(desk);

    const plaster = plasterTexture();
    plaster.repeat.set(5, 2);
    const wall = new THREE.Mesh(
      new THREE.PlaneGeometry(5200, 2400),
      new THREE.MeshStandardMaterial({ color: 0x262626, roughness: 1, bumpMap: plaster, bumpScale: 0.5, dithering: true }),
    );
    wall.position.set(0, 1150, -1150);
    wall.receiveShadow = true;
    this.scene.add(wall);

    // 画外左后方的暖色台灯：不出现灯具本体，只在墙面与桌面留下柔和暖光（避免抢视觉中心）
    const wash = new THREE.SpotLight(0xffb072, 5.0, 0, 0.55, 1.0, 0);
    wash.position.set(-1500, 900, -300);
    const washTarget = new THREE.Object3D();
    washTarget.position.set(-700, 380, -1150);
    this.scene.add(washTarget);
    wash.target = washTarget;
    this.scene.add(wash);
    const deskGlow = new THREE.PointLight(0xffa860, 1.6e5, 0, 2);
    deskGlow.position.set(-1050, 300, -700);
    this.scene.add(deskGlow);

    // 背景右后：两本布面精装书 + 陶瓷杯（克制陈设，低饱和）
    const cloth = (c: number) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.92 });
    const book1 = new THREE.Mesh(new RoundedBoxGeometry(230, 30, 160, 3, 4), cloth(0x26302b));
    book1.position.set(420, 15, -640);
    book1.rotation.y = 0.18;
    const book2 = new THREE.Mesh(new RoundedBoxGeometry(205, 24, 145, 3, 4), cloth(0x6f675b));
    book2.position.set(412, 42, -636);
    book2.rotation.y = 0.05;
    for (const b of [book1, book2]) {
      b.castShadow = true;
      b.receiveShadow = true;
      this.scene.add(b);
    }
    const mugProfile = [
      [0.001, 0],
      [38, 0],
      [40, 3],
      [41, 92],
      [37.5, 92],
      [36.5, 6],
      [0.001, 6],
    ].map(([x, y]) => new THREE.Vector2(x, y));
    const mug = new THREE.Mesh(
      new THREE.LatheGeometry(mugProfile, 64),
      new THREE.MeshPhysicalMaterial({ color: 0x3a3936, roughness: 0.5, clearcoat: 0.25 }),
    );
    const handle = new THREE.Mesh(new THREE.TorusGeometry(22, 5.5, 16, 48, Math.PI), mug.material);
    handle.rotation.z = -Math.PI / 2;
    handle.position.set(41, 48, 0);
    const cup = new THREE.Group();
    cup.add(mug, handle);
    cup.position.set(-700, 0, -450);
    cup.rotation.y = 0.9;
    cup.traverse((o) => {
      o.castShadow = true;
      o.receiveShadow = true;
    });
    this.scene.add(cup);
  }

  // ───────────── 产品 ─────────────
  private buildProduct(parts: Map<PartName, THREE.BufferGeometry>) {
    const whiteResin = new THREE.MeshPhysicalMaterial({
      color: 0xeaeae7,
      roughness: 0.58,
      metalness: 0,
      specularIntensity: 0.45,
      sheen: 0.2,
      sheenRoughness: 0.8,
      sheenColor: 0xffffff,
    });
    const knobResin = whiteResin.clone();
    knobResin.roughness = 0.52;
    const buttonResin = whiteResin.clone();
    buttonResin.color.set(0xd9d8d4);
    const graphite = new THREE.MeshPhysicalMaterial({
      color: 0x2b2d30,
      roughness: 0.5,
      metalness: 0,
      specularIntensity: 0.4,
      sheen: 0.15,
      sheenRoughness: 0.9,
      sheenColor: 0x9aa0a8,
    });
    const matFor: Record<PartName, THREE.Material> = {
      front: whiteResin,
      left_knob: knobResin,
      right_knob: knobResin,
      buttons: buttonResin,
      rear: graphite,
      left_support: graphite,
      right_support: graphite,
      base: graphite,
    };
    for (const [name, geo] of parts) {
      const m = new THREE.Mesh(geo, matFor[name]);
      m.name = name;
      m.castShadow = true;
      m.receiveShadow = true;
      this.product.add(m); // 不设置任何逐件变换
    }
    this.product.add(this.buildScreenInsert());
    this.product.position.copy(ASSEMBLY_OFFSET);
    this.scene.add(this.product);

    // 接触阴影（由底座真实投影外形生成），贴在桌面上
    const cs = new THREE.Mesh(
      new THREE.PlaneGeometry(CONTACT_EXTENT.x, CONTACT_EXTENT.z),
      new THREE.MeshBasicMaterial({
        map: contactShadowTexture(parts.get('base')!),
        transparent: true,
        depthWrite: false,
        color: 0x000000,
        opacity: 0.75,
        toneMapped: false,
      }),
    );
    (cs.material as THREE.MeshBasicMaterial).alphaMap = (cs.material as THREE.MeshBasicMaterial).map;
    (cs.material as THREE.MeshBasicMaterial).map = null;
    cs.rotation.x = -Math.PI / 2;
    cs.position.set(0, 0.05, 0);
    cs.renderOrder = 1;
    this.scene.add(cs);
  }

  /** 屏幕总成：LCD 黑色面板 → 有效显示区（原画面纹理）→ 盖板丝印黑边 → 玻璃反射层 */
  private buildScreenInsert() {
    const g = new THREE.Group();
    const S = SCREEN_SPEC;
    const black = new THREE.MeshBasicMaterial({ color: 0x000000 });

    // LCD 模组黑色非显示区：只铺在前壳通孔范围内（76mm），不与 z=14 台阶重叠
    const panel = new THREE.Mesh(new THREE.PlaneGeometry(75.5, 75.5, 16, 16), black);
    panel.name = 'lcd-panel';
    panel.position.set(S.coverCenter[0], S.coverCenter[1], S.zPanel);
    g.add(panel);

    this.screenTex = new THREE.CanvasTexture(this.compositor.canvas);
    this.screenTex.colorSpace = THREE.SRGBColorSpace;
    this.screenTex.anisotropy = 8;
    this.screenTex.generateMipmaps = true;
    this.screenTex.minFilter = THREE.LinearMipmapLinearFilter;
    const lcd = new THREE.Mesh(
      new THREE.PlaneGeometry(S.lcdActive[0], S.lcdActive[1]),
      new THREE.MeshBasicMaterial({ map: this.screenTex, color: new THREE.Color(0.86, 0.86, 0.86) }),
    );
    lcd.name = 'lcd-active-area';
    lcd.position.set(S.coverCenter[0] + S.lcdOffset[0], S.coverCenter[1] + S.lcdOffset[1], S.zLcd);
    g.add(lcd);

    // 盖板背面丝印：84×84 外形，挖出 CG-VA 开窗（用四条矩形拼成，避免三角化细缝）
    const hw = S.coverGlass[0] / 2,
      hh = S.coverGlass[1] / 2;
    const ww = S.window[0] / 2,
      wh = S.window[1] / 2,
      oy = S.lcdOffset[1];
    const inkMat = new THREE.MeshStandardMaterial({ color: 0x020203, roughness: 0.3 });
    const ink = new THREE.Group();
    ink.name = 'cover-ink';
    const strip = (x0: number, x1: number, y0: number, y1: number) => {
      // 细分成接近正方形的三角形，避免狭长三角形在软件光栅化下出现细缝
      const w = x1 - x0,
        h = y1 - y0;
      const m = new THREE.Mesh(
        new THREE.PlaneGeometry(w + 0.02, h + 0.02, Math.max(1, Math.round(w / 4)), Math.max(1, Math.round(h / 4))),
        inkMat,
      );
      m.position.set((x0 + x1) / 2, (y0 + y1) / 2, 0);
      ink.add(m);
    };
    strip(-hw, hw, oy + wh, hh); // 上
    strip(-hw, hw, -hh, oy - wh); // 下
    strip(-hw, -ww, oy - wh, oy + wh); // 左
    strip(ww, hw, oy - wh, oy + wh); // 右
    ink.position.z = S.zInk;
    g.add(ink);

    // 盖板外表面：只叠加反射（黑色漫反射 + 菲涅尔镜面），透出下方屏幕内容
    const glass = new THREE.Mesh(
      new THREE.PlaneGeometry(S.coverGlass[0], S.coverGlass[1]),
      new THREE.MeshPhysicalMaterial({
        color: 0x000000,
        roughness: 0.035,
        metalness: 0,
        ior: 1.52,
        specularIntensity: 1,
        envMap: this.glassEnv,
        envMapIntensity: 1.0,
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    glass.name = 'cover-glass';
    glass.position.z = S.zGlass;
    glass.renderOrder = 2;
    g.add(glass);
    return g;
  }

  // ───────────── 灯光 ─────────────
  // three.js 物理光照：漫反射 = albedo/π × 照度，因此强度数值约为“期望亮度 × π”
  private buildLights() {
    const target = new THREE.Object3D();
    target.position.set(0, 50, 0);
    this.scene.add(target);

    // 主光：左前上方的柔和聚光（大半影），在桌面上自然衰减成光池
    // decay=2：距离平方衰减，让产品正面从上到下有自然的明暗过渡
    const key = new THREE.SpotLight(0xfff6ef, 5.3 * 1150 * 1150, 0, 0.3, 0.95, 2);
    key.position.set(-380, 900, 640);
    key.target = target;
    key.castShadow = true;
    key.shadow.mapSize.set(4096, 4096);
    key.shadow.camera.near = 600;
    key.shadow.camera.far = 1600;
    key.shadow.bias = -0.00008;
    key.shadow.normalBias = 0.25;
    key.shadow.radius = 9;
    key.shadow.blurSamples = 20;
    this.scene.add(key);

    // 轮廓光：右后方冷色，勾出石墨灰后壳与支架边缘
    const rim = new THREE.SpotLight(0xd3ddff, 9.0, 0, 0.35, 0.9, 0);
    rim.position.set(620, 420, -760);
    rim.target = target;
    this.scene.add(rim);

    // 右前方低位补光：提亮右侧面（BOOT/RST 面）与旋钮齿纹，不产生阴影
    const fill = new THREE.DirectionalLight(0xffe9d6, 1.15);
    fill.position.set(700, 160, 380);
    fill.target = target;
    this.scene.add(fill);
  }

  private buildComposer() {
    // 不用 MSAA：SwiftShader 软件渲染下 MSAA 会在共边处出现细缝；改为 SMAA 后处理抗锯齿
    const rt = new THREE.WebGLRenderTarget(WIDTH, HEIGHT, { type: THREE.HalfFloatType });
    this.composer = new EffectComposer(this.renderer, rt);
    this.composer.setPixelRatio(1);
    this.composer.setSize(WIDTH, HEIGHT);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.dof = new DofPass(this.scene, this.camera, WIDTH, HEIGHT);
    this.composer.addPass(this.dof);
    this.composer.addPass(new ShaderPass(VignetteShader));
    this.composer.addPass(new OutputPass());
    this.composer.addPass(new SMAAPass());
  }

  setCamera(p: CameraPose) {
    const yaw = THREE.MathUtils.degToRad(p.yaw);
    const pitch = THREE.MathUtils.degToRad(p.pitch);
    const t = new THREE.Vector3(...p.target);
    const dir = new THREE.Vector3(Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch));
    this.camera.position.copy(t).addScaledVector(dir, p.dist);
    this.camera.fov = p.fov;
    this.camera.updateProjectionMatrix();
    this.camera.lookAt(t);
    this.camera.updateMatrixWorld();
    this.dof.focus = p.focus ?? p.dist;
  }

  /** 渲染一帧（同步）。调用后 renderer.domElement 即为该帧画面 */
  render() {
    if (this.compositor.version !== this.screenVersion) {
      this.screenVersion = this.compositor.version;
      this.screenTex.needsUpdate = true;
    }
    this.composer.render();
  }
}
