/* 最小类型声明：Spine 官方 runtime（public/vendor/spine-webgl.js）以全局 `spine` 暴露。 */
/* eslint-disable @typescript-eslint/no-explicit-any */
declare namespace spine {
  const Physics: { update: any; none: any; pose: any; reset: any };
  class AssetManager {
    constructor(gl: WebGLRenderingContext, pathPrefix?: string);
    loadBinary(path: string): void;
    loadTextureAtlas(path: string): void;
    isLoadingComplete(): boolean;
    hasErrors(): boolean;
    getErrors(): Record<string, string>;
    require(path: string): any;
    get(path: string): any;
  }
  class SceneRenderer {
    constructor(canvas: HTMLCanvasElement, gl: WebGLRenderingContext, twoColorTint?: boolean);
    camera: { position: { x: number; y: number }; viewportWidth: number; viewportHeight: number; update(): void };
    begin(): void;
    end(): void;
    drawSkeleton(s: Skeleton, premultipliedAlpha?: boolean, slotRangeStart?: number, slotRangeEnd?: number): void;
  }
  class AtlasAttachmentLoader {
    constructor(atlas: any);
  }
  class SkeletonBinary {
    constructor(loader: AtlasAttachmentLoader);
    readSkeletonData(binary: any): SkeletonData;
  }
  interface SlotData {
    name: string;
    index: number;
  }
  interface Slot {
    data: SlotData;
  }
  interface Animation {
    name: string;
    duration: number;
  }
  class SkeletonData {
    version: string;
    animations: Animation[];
    physicsConstraints: unknown[];
  }
  class Skeleton {
    constructor(data: SkeletonData);
    x: number;
    y: number;
    drawOrder: Slot[];
    setSkinByName(n: string): void;
    setToSetupPose(): void;
    updateWorldTransform(physics: any): void;
  }
  class AnimationStateData {
    constructor(d: SkeletonData);
  }
  interface TrackEntry {
    trackTime: number;
  }
  class AnimationState {
    constructor(d: AnimationStateData);
    setAnimation(track: number, name: string, loop: boolean): TrackEntry;
    apply(s: Skeleton): boolean;
  }
}
