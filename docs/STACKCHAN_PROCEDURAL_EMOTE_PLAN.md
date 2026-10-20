# StackChan 风格程序化表情绘制方案

> **版本**: 1.1  
> **日期**: 2025-02  
> **目标**: 在 GFX pipeline 上实现 StackChan 风格的眼睛、嘴巴、眨眼、呼吸，替代 EAF 动画表情，支持按屏幕尺寸自适应。

---

## 重要说明：与 Emote 的关系

**EmoteDisplay 的实现方式与程序化绘制本质不同**：

| | EmoteDisplay（现有） | 程序化绘制（目标） |
|---|---|---|
| 数据来源 | 预制 EAF 动画、图标图片 | 运行时实时计算 |
| 核心动作 | 加载资源 → 交给 GFX 显示 | 每帧绘制到 buffer → 再交给 GFX |
| 刷新驱动 | gfx_anim 自带 | 需自己用 esp_timer |
| 画图逻辑 | 无 | 软件光栅化（圆、圆角矩形等）|

因此：**程序化绘制核心部分独立设计，不参考 emote**。  
**仅“集成层”**（如何接到 GFX pipeline、Display 接口、layout）参考 emote_display 的接入方式。

---

## 参考材料与文件路径

以下为可参照的实现，实施时可直接对照逻辑与公式。

### （一）stack-chan（Moddable/TypeScript）— 程序化绘制逻辑主要参考

与目标最接近：矢量路径 → 光栅化，无 LVGL，逻辑可迁移到 C++。

| 路径 | 可参照内容 |
|------|------------|
| `stack-chan/firmware/stackchan/renderers/simple-face.ts` | **眼睛**：`path.arc(cx, cy, radius, 0, 2π)`；**眼皮**：按 emotion 用 rect/梯形（NEUTRAL=rect，ANGRY/SAD=梯形，SLEEPY=半高 rect，HAPPY=上下两 rect）；**嘴巴**：`w = minWidth+(maxWidth-minWidth)*(1-open)`，`h = minHeight+(maxHeight-minHeight)*open`，`path.rect()`；**坐标**：左眼 (90,93)、右眼 (230,96)、嘴 (160,148) @ 320 宽 |
| `stack-chan/firmware/stackchan/renderers/modifier.ts` | **Blink**：`linearInEaseOut` 插值，`openMin/openMax` 开眼间隔、`closeMin/closeMax` 闭眼时长，随机切换；**Breath**：`face.breath = sin(2π*time/duration)` 量化；**Saccade**：随机更新 gazeX/Y |
| `stack-chan/firmware/stackchan/renderers/renderer-base.ts` | **FaceContext** 结构（eyes.open、mouth.open、emotion、breath、theme）；**Layer** 分层（primary=眼睛嘴，secondary=眼皮）；渲染顺序 |
| `stack-chan/firmware/stackchan/renderers/dog-face.ts` | **可选**：嘴巴用 `path.bezierCurveTo` 实现弧线嘴，眼皮用 `path.ellipse`；可供进阶造型参考 |

### （二）1.27-xiaozhi main/stackchan（C++ LVGL）— 表情映射与布局常量

使用 LVGL 控件，绘制方式不同，可参考表情语义与布局数值。

| 路径 | 可参照内容 |
|------|------------|
| `main/stackchan/avatar/skins/default/eyes.cpp` | **表情映射**：Neutral(100,0)、Happy(72,1550)、Angry(70,450)、Sad(70,-400)、Doubt(75,0)、Sleepy(35,-50)；**布局**：`_eye_pos(-70,-16)`、`_eye_size_limit(8,32)`；**weight→眼皮**：`map_range(weight,0,100,0,eyelid_height)` |
| `main/stackchan/avatar/skins/default/mouth.cpp` | **嘴巴布局**：`_mouth_pos(0,26)`；**weight→尺寸**：宽 90→60、高 6→50、圆角 0→16 |

### （三）emote_display — 集成层参考

| 路径 | 可参照内容 |
|------|------------|
| `main/display/emote_display.cc` | GFX 对象创建、DisplayLockGuard 用法、SetupUI、SetEyes/SetIcon、AddLayoutData、SetPowerSaveMode |
| `main/display/emote_display.h` | AssetData、Display 接口、AddLayoutData 签名 |

> **路径说明**：stack-chan 为工程根目录下的 `stack-chan` 文件夹（与 1.27-xiaozhi 同级）；其余路径相对 `1.27-xiaozhi` 根目录。

---

## 设计目标（表情外观描述）

以下根据 `simple-face.ts`、`eyes.cpp`、`mouth.cpp` 的逻辑整理，作为实现时的**视觉目标**。整体为**极简脸**：双眼 + 嘴，无眉毛/鼻子（可后续扩展）。

### 整体布局（320×240 基准）

- **左眼**：约 (90, 93)，半径 8
- **右眼**：约 (230, 96)，半径 8  
- **嘴巴**：居中 (160, 148)
- **分层**：先画眼睛和嘴（主色），再在上层画眼皮（背景色遮罩，模拟闭眼）

### 眼睛外观

- **眼球**：实心圆，主色（通常白）
- **眼皮**：与背景同色的遮罩，从眼球上方往下遮挡；形状因 emotion 不同：

| 表情 | 眼皮形状（simple-face 逻辑） | 眼开合 | 眼倾斜（eyes.cpp rotation） |
|------|------------------------------|--------|-----------------------------|
| **Neutral** | 矩形，高度由 eye.open 决定 | 全开(100) | 0° |
| **Happy** | 上下两块矩形（眯眼效果） | 略眯(72) | 眼尾上扬 |
| **Angry** | 梯形，左高右低 | 略眯(70) | 眉梢上挑 |
| **Sad** | 梯形，左低右高（下垂） | 略眯(70) | 眼尾下垂 |
| **Doubt** | 同 Neutral | 稍眯(75) | 正视 |
| **Sleepy** | 半高矩形（半闭） | 半闭(35) | 微垂 |

### 嘴巴外观

- **闭嘴**（mouth.open≈0）：窄横条，宽约 90、高约 6（或 8）
- **张嘴**（mouth.open≈1）：扁椭圆，宽约 50～60、高约 50～58
- **过渡**：w = 90→50、h = 6→58 线性插值；圆角可由 0→16（mouth.cpp）

### 眨眼

- 随机间隔（如 4～5 秒）触发，闭眼时长约 0.2～0.4 秒
- 闭眼过程：eye.open 从 1 线性或缓动插值到约 0.2
- 开眼过程：反向插值回 1

### 呼吸（可选）

- 整脸轻微上下偏移（如 ±3 像素），周期约 6 秒，正弦变化

### 简化实现建议

Phase 1 可先统一用**矩形眼皮**（Neutral 形状），通过 weight 控制遮挡高度表达眯眼，暂不做 ANGRY/SAD/HAPPY 的梯形/分块眼皮；待基础效果确认后再按 simple-face 增加形状变化。

---

## 一、程序化绘制核心（独立设计，不参考 emote）

### 1.1 整体思路

每帧在**内存 buffer**中用代码绘制眼睛+嘴巴 → 生成 RGB565 位图 → 通过 `gfx_img_set_src` 显示。  
绘制逻辑与 emote 的「贴图/播动画」完全无关，需自建。

### 1.2 StackChan 绘制逻辑摘要

**眼睛**：位置 (-70,-16)/(70,-16)，weight 控制眼皮，rotation 表示表情。参考 `main/stackchan/avatar/skins/default/eyes.cpp` 的表情映射；**路径化绘制**参考 `stack-chan/.../simple-face.ts` 的 `createEyePart`、`createEyelidPart`（按 emotion 切换眼皮形状）。  
**嘴巴**：位置 (0,26)，weight 控制宽高、圆角。参考 `mouth.cpp` 的尺寸映射；**公式**参考 simple-face 的 `createMouthPart`（w/h 与 open 线性插值）。

### 1.3 绘制算法（软件光栅化）

- **buffer**：RGB565，大小约 200×120（仅覆盖表情区域）
- **图元**：`fill_circle`（眼睛，对应 simple-face 的 `path.arc`）、`fill_rounded_rect`（嘴巴）、`fill_rect`（清空、眼皮）
- **动画**：esp_timer 约 33fps 驱动。**眨眼**参考 `modifier.ts` 的 `createBlinkModifier`（openMin/Max、closeMin/Max、linearInEaseOut 插值）；**呼吸**参考 `createBreathModifier`（sin 周期、可量化）；**Saccade**（视线微动）可选

### 1.4 模块职责（与 emote 无关）

- 输入：屏幕尺寸、当前 emotion、blink 状态
- 输出：绘制好的 RGB565 buffer
- 不涉及：gfx_obj、Display、layout —— 这些属于集成层

---

## 二、集成层（仅此处参考 emote_display）

程序化模块只负责「画到 buffer」。如何接到现有工程，**参考 emote_display** 的接入方式。

### 2.1 参考要点（来自 `main/display/emote_display.cc`、`emote_display.h`）

| 参考项 | emote 做法 | 程序化集成时 |
|--------|------------|--------------|
| GFX 对象 | `static gfx_obj_t*` 全局 | 新增 `g_obj_img_face`、`g_face_img_dsc` |
| 创建时机 | `SetupUI()` 内 `gfx_img_create` | 程序化模式下创建 `g_obj_img_face` 替代 `g_obj_anim_eye` |
| 修改 GFX | 全在 `DisplayLockGuard` 内 | timer 回调内 Lock → Update → gfx_img_set_src → Unlock |
| 布局 | `AddLayoutData` 按 name 映射 | `"eye_anim"` 映射到 `g_obj_img_face` |
| 省电 | `SetPowerSaveMode` 调 gfx_anim_stop | 程序化模式下调 StopTimer/StartTimer |
| width/height | 构造时传入，用于 gfx_cfg | 传入 procedural 的 Init，或 `display->width()` |

### 2.2 集成流程（薄对接）

1. **SetupUI**：`#if CONFIG_USE_PROCEDURAL_STACKCHAN_EMOTE` 时创建 `g_obj_img_face`，调用 `procedural_emote::Init(width, height)`，不创建 `g_obj_anim_eye`。
2. **esp_timer**：周期回调内 `DisplayLockGuard` → `procedural_emote::Update()` → `gfx_img_set_src(g_obj_img_face, &g_face_img_dsc)`。
3. **SetEmotion**：程序化模式下直接 `procedural_emote::SetEmotion(emotion)`，不查 emoji_data_map_。
4. **SetPowerSaveMode**：程序化模式下 `StopTimer()` / `StartTimer()`。
5. **AddLayoutData**：`"eye_anim"` 映射到 `g_obj_img_face`，沿用 layout.json 配置。

### 2.3 需验证（GFX 侧）

- `gfx_img_set_src` 每帧更新同一 buffer 是否稳定
- `gfx_img` 是否要求 RGB565A8 / header 格式

---

## 三、文件结构

```
main/display/
├── emote_display.cc/h      # 修改：加入程序化分支、timer、集成调用
├── procedural_emote.cc      # 新增：绘制核心（fill_circle、fill_rounded_rect、眨眼、表情映射）
└── procedural_emote.h       # 新增：Init、Update、SetEmotion、StopTimer、StartTimer、GetBuffer 等
```

程序化模块自成一格，不模仿 emote 的类结构；集成逻辑写在 emote_display.cc 的分支里。

---

## 四、坐标与尺寸自适应

以 320×240 为基准缩放，公式见原方案第四节。双指缩放预留 zoom_factor 接口（Phase 2）。

---

## 五、Kconfig 与风险

- `CONFIG_USE_PROCEDURAL_STACKCHAN_EMOTE`：启用时用程序化替换 EAF 眼睛。
- 风险：每帧 set_src 稳定性、CPU 占用、gfx 图片格式，实施时需实测。

---

## 六、实施步骤

1. 实现 procedural_emote：fill_circle、fill_rounded_rect、表情映射、眨眼。
2. 验证 gfx_img 每帧 set_src 是否可行。
3. 在 emote_display.cc 中加集成分支：SetupUI、timer、SetEmotion、SetPowerSaveMode、AddLayoutData。
4. 按屏幕尺寸做缩放与 Kconfig。

---

**总结**：程序化绘制核心**独立设计**；**集成层**参考 emote_display 的 GFX 接入方式（对象创建、Lock、layout、省电），不做更多借鉴。
