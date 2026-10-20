/**
 * 景深后期（薄透镜近似 + 深度感知的 scatter-as-gather）。
 * 与 three 自带 BokehPass 的区别：对焦清晰的前景像素不会被“抹”进背景，
 * 背景也不会渗到前景边缘，因此产品轮廓不会出现白色光晕。
 */
import * as THREE from 'three';
import { Pass, FullScreenQuad } from 'three/examples/jsm/postprocessing/Pass.js';

const SAMPLES = 56;

const DofShader = {
  uniforms: {
    tColor: { value: null as THREE.Texture | null },
    tDepth: { value: null as THREE.Texture | null },
    resolution: { value: new THREE.Vector2(1, 1) },
    cameraNear: { value: 1 },
    cameraFar: { value: 1000 },
    focus: { value: 400 },
    cocScale: { value: 20 }, // 无穷远处的弥散圆半径（像素）
    maxCoc: { value: 22 },
  },
  vertexShader: /* glsl */ `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
  fragmentShader: /* glsl */ `
    #include <packing>
    #define SAMPLES ${SAMPLES}
    uniform sampler2D tColor; uniform sampler2D tDepth;
    uniform vec2 resolution; uniform float cameraNear; uniform float cameraFar;
    uniform float focus; uniform float cocScale; uniform float maxCoc;
    varying vec2 vUv;
    float viewDist(vec2 uv){
      float d = texture2D(tDepth, uv).x;
      return -perspectiveDepthToViewZ(d, cameraNear, cameraFar);
    }
    float coc(float dist){ return min(maxCoc, cocScale * abs(1.0 - focus / dist)); }
    void main(){
      float d0 = viewDist(vUv);
      float c0 = coc(d0);
      vec3 center = texture2D(tColor, vUv).rgb;
      // 合焦区域（产品）直接保留原像素：清晰且省算力
      if (c0 < 0.6) { gl_FragColor = vec4(center, 1.0); return; }
      vec4 acc = vec4(center, 1.0);
      const float GOLDEN = 2.39996323;
      // 采样数随弥散圆面积增长
      float n = clamp(c0 * c0 * 0.9, 8.0, float(SAMPLES));
      for (int i = 1; i < SAMPLES; i++) {
        float fi = float(i);
        if (fi >= n) break;
        float r = sqrt(fi / n) * c0;
        float a = fi * GOLDEN;
        vec2 o = vec2(cos(a), sin(a)) * r / resolution;
        vec2 uv = vUv + o;
        float ds = viewDist(uv);
        float cs = coc(ds);
        // 样本在当前像素后方时，其扩散不超过当前像素自身的弥散圆（防止背景渗入前景）
        float ce = ds > d0 ? min(cs, c0) : cs;
        float w = smoothstep(r - 1.0, r + 0.5, ce);
        acc += vec4(texture2D(tColor, uv).rgb * w, w);
      }
      gl_FragColor = vec4(acc.rgb / acc.a, 1.0);
    }`,
};

export class DofPass extends Pass {
  private quad: FullScreenQuad;
  private material: THREE.ShaderMaterial;
  private depthTarget: THREE.WebGLRenderTarget;
  private depthMaterial = new THREE.MeshBasicMaterial({ colorWrite: false });
  focus = 400;
  /** 以 400mm 对焦时、无穷远背景的弥散圆半径（像素） */
  strength = 22;

  constructor(
    private scene: THREE.Scene,
    private camera: THREE.PerspectiveCamera,
    width: number,
    height: number,
  ) {
    super();
    this.material = new THREE.ShaderMaterial({
      uniforms: THREE.UniformsUtils.clone(DofShader.uniforms),
      vertexShader: DofShader.vertexShader,
      fragmentShader: DofShader.fragmentShader,
    });
    this.quad = new FullScreenQuad(this.material);
    const depthTexture = new THREE.DepthTexture(width, height, THREE.FloatType);
    this.depthTarget = new THREE.WebGLRenderTarget(width, height, { depthTexture, depthBuffer: true });
    this.material.uniforms.resolution.value.set(width, height);
  }

  render(renderer: THREE.WebGLRenderer, writeBuffer: THREE.WebGLRenderTarget, readBuffer: THREE.WebGLRenderTarget) {
    // 深度
    const prevOverride = this.scene.overrideMaterial;
    const prevBg = this.scene.background;
    this.scene.overrideMaterial = this.depthMaterial;
    this.scene.background = null;
    renderer.setRenderTarget(this.depthTarget);
    renderer.clear();
    renderer.render(this.scene, this.camera);
    this.scene.overrideMaterial = prevOverride;
    this.scene.background = prevBg;

    const u = this.material.uniforms;
    u.tColor.value = readBuffer.texture;
    u.tDepth.value = this.depthTarget.depthTexture;
    u.cameraNear.value = this.camera.near;
    u.cameraFar.value = this.camera.far;
    u.focus.value = this.focus;
    // 同一支镜头：对焦越远，背景弥散越小（∝ 1/对焦距离）
    const k = this.strength * (400 / this.focus);
    u.cocScale.value = k;
    u.maxCoc.value = Math.max(1.5, Math.min(24, k));
    renderer.setRenderTarget(this.renderToScreen ? null : writeBuffer);
    this.quad.render(renderer);
  }

  dispose() {
    this.quad.dispose();
    this.material.dispose();
    this.depthTarget.dispose();
  }
}
