# 桌面 AI 伙伴 · 宣传片前端（阶段一：7 秒开场）

React + TypeScript + Vite + Three.js。镜头、屏幕、字幕、声音都由同一条时间轴驱动：
任意画面 = `render(t)`，没有累积状态，固定时间截图逐像素可复现。

> 当前阶段只交付 **0–7 秒开场** 和 3 张关键画面；对话画面是为 14–21 秒段准备的**草稿静帧**。
> 等开场确认后，再扩展完整 30 秒、配音与最终导出。

---

## 1. 启动

需要 Node.js ≥ 20.19。

```bash
npm install
npm run dev          # 浏览器打开 http://localhost:5173
```

播放器（控件都在成片画布之外，不会进入任何导出帧）：

| 操作 | 说明 |
|---|---|
| 播放 / 暂停 | 按钮或空格 |
| 拖动时间轴 | 以 1/30 秒为步长 |
| ◀ 1帧 / 1帧 ▶ | 或键盘 ← / → |
| 字幕 / 声音 | 开关；开场阶段按要求没有文字和声音，开关在完整版生效 |
| 截图当前帧 | 下载 1920×1080 PNG（与导出帧完全相同） |
| 关键画面 | 一键切到 3 张验收静帧 |
| `?t=6.6` | 地址栏参数，直接打开指定时间 |

## 2. 可复现导出

```bash
npm run build
npx playwright install chromium      # 首次需要
npm run stills                       # → output/stills/*.png（3 张关键画面）
npm run export:opening               # → output/opening-7s.mp4（需要 ffmpeg 在 PATH 中）
node scripts/render.mjs --dist dist --at 4.2   # 任意单帧 → output/frame_4.200.png
```

`scripts/render.mjs` 的做法：内置静态服务器打开 `dist/index.html?mode=export`（页面上只有成片画布）→
无头 Chromium 以软件 WebGL（SwiftShader）逐帧调用 `window.__promo.renderFrame(i/30)` → PNG 序列 →
ffmpeg 编码 H.264（1920×1080、30fps、yuv420p、CRF 14）。帧时间严格由帧号计算。

- 默认用软件渲染，跨机器结果一致，但慢（2 核约 4 秒/帧，7 秒开场约 15 分钟）。
- 加 `--gpu` 改用本机显卡，速度快很多，不同显卡之间像素可能有极细微差异。
- `--keep-frames` 保留 PNG 序列；`--no-subtitles` 导出无字幕版本。

## 3. 目录

```
public/
  assets/models/parts-data.json   原 8 零件三角网格（未改动）
  assets/models/dimensions.json   原尺寸与屏幕规格
  assets/spine/                   原 nvhai.skel / nvhai.atlas / texture.png / room.png
  assets/boot/000–079.png         原开机动画 80 帧
  vendor/spine-webgl.js           Spine 官方 runtime（素材包提供，兼容 4.2）
src/
  core/timeline.ts      ★ 统一时间轴：镜头、屏幕状态、对话、音轨、静帧
  core/engine.ts        t → 1920×1080 成片帧
  core/audio.ts         可替换音轨接口（WebAudio，与时间轴同步）
  scene/productModel.ts parts-data.json 加载与校验、屏幕总成尺寸
  scene/stage.ts        桌面场景、材质、灯光、镜头、后期
  scene/dofPass.ts      深度感知景深（产品轮廓无光晕）
  scene/textures.ts     程序化胡桃木 / 墙面 / 由底座真实外形生成的接触阴影
  screen/spineIdle.ts   原 Spine idle 播放（可按时间精确定位）
  screen/screenCompositor.ts  黑屏 / 开机帧 / 壁纸+角色 → 同一张屏幕纹理
  overlay/overlay.ts    对话框（直接画进成片帧）
  player/               播放器界面
scripts/render.mjs      静帧 / 单帧 / MP4 导出
```

## 4. 素材核对记录

**模型（parts-data.json）** — 已检查字段，不是 glTF：数组 8 项，每项 `positions`/`normals` 为 base64 Float32（xyz），
`indices` 为 base64 Uint32，`bounds` 含包围盒和顶点/三角数。加载时逐件校验长度和包围盒（误差 > 0.01mm 直接报错）。
单位 mm、Y 向上、+Z 为屏幕正面。8 件共用装配坐标，**不逐件居中、不缩放、不旋转**，整机只做一次平移（底座底面 y=-67 → 桌面 y=0）。
整机 120×119×66mm、底座 120×66×12mm、屏幕机壳 104×104（前壳 15 + 后壳 11.6）均与 dimensions.json 一致。
BOOT/RST 按钮件位于 +X 侧面，摄像头开孔在前壳顶部中央，都按原坐标渲染，只在机位真实可见时出现（靠遮挡自然决定，没有额外显隐逻辑）。

**屏幕总成**（dimensions.json → screen_insert，前壳实测有 84×84、深 1mm 的盖板凹槽，台阶面 z=14）：

| 层 | 尺寸 / 位置 |
|---|---|
| LCD 有效区（原画面纹理） | 71.14 × 69.82mm，中心 (0, +1.0)，z = 14.11 |
| 盖板丝印开窗 | 71.64 × 70.32mm，四周黑边 左右 6.18 / 上 5.84 / 下 7.84mm |
| 盖板外表面（只叠加反射） | 84 × 84mm，z = 14.92（略低于前框面 z=15） |

整块屏幕内容是一张 640×640 画布纹理，整体映射到有效区；原素材是正方形，有效区宽高比 1.019，映射时随面板等比例铺满（与实机帧缓冲铺满面板一致）。

**Spine** — 运行时读取：骨骼版本 4.2.43，idle 5.333s，**没有物理约束**，因此每帧 `setToSetupPose + trackTime = t` 即可精确定位，拖动 / 截图可复现。
full-screen.html 的布局参数已复核后沿用：skeleton (170.764, 42.510)、320 视口 → 640 画布；身体/上臂/衣领 4 个槽位在 room.png 桌沿（640 画布 y=536）以下裁切，
前臂与手不裁切、搭在桌面上。逐帧检查 idle 全程：手臂完整，桌沿与壁纸对位正确。

**开机动画** — 80 帧，原 20fps / 4s，整体 1.6 倍速：第 `floor((t−3)×32)` 帧，3.0–5.5s 恰好 80 帧全部播放、不截断。

**开场时间轴**：0–3s 黑屏（玻璃上只有环境反射缓慢滑过）；3–5.5s 原开机动画；5.5s 起壁纸与角色作为同一张纹理在 0.2s 内一起亮起，之后原 idle 持续微动到 7s。
镜头 0–7s 为一次连续推镜（单一缓动、固定焦距、无抖动、无变焦），从 930mm 推到 395mm，方位 34°→25°。

## 5. 假设与说明

- 按钮件颜色：资料只规定前盖、旋钮、后壳/支架/底座，按钮件取与前盖同系的浅灰白树脂。
- 摄像头开孔：保留 CAD 原开孔，没有另加镜头模型。
- “BOOT/RST” 字样来自按钮件 CAD 本身的凸起字，不另加贴图。
- 背景只有画外暖色台灯的光、一只陶瓷杯、两本书（大部分镜头中在画外），均为程序化几何，不是产品。
- 抗锯齿用 SMAA：软件渲染下 MSAA 会在共边处出现细缝，已验证并改用后处理。
- 字体：按 Noto Sans SC → 思源黑体 → 苹方 → 微软雅黑 顺序回退；需跨机器完全一致时，请在两台机器装同一字体。
- 声音：开场阶段按要求无配音、无音乐。完整版的画外音 / 音效 / 配乐在 `timeline.ts` 的 `AudioCue` 列表里登记文件即可接入；素材包里的 boot.ogg 暂未使用。
