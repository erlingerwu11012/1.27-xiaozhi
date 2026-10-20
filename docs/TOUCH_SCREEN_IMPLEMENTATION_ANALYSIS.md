# StackChan 触摸屏功能实现分析方案

> **目的**：全盘扫描并定位源码中负责处理触摸事件的文件和函数，解释如何区分「摸脸」与「按键」的逻辑。

---

## 一、项目结构概览

当前 workspace 包含多个相关项目：

| 项目 | 路径 | 语言/框架 | 用途 |
|------|------|-----------|------|
| **1.27-xiaozhi** | `1.27-xiaozhi/` | C++ / ESP-IDF / LVGL | 小智固件（含 StackChan 融合） |
| **stack-chan** | `stack-chan/` | TypeScript / Moddable | StackChan 官方 Moddable 固件 |
| **esp-box** | `esp-box/` | C / ESP-IDF | ESP Box 参考项目 |

---

## 二、1. 初始化代码

### 2.1 1.27-xiaozhi（ESP32 C++）

**未使用 M5.Touch / M5Unified**。各板型使用 ESP-IDF 的 `esp_lcd_touch_*` 或自研 I2C 驱动。

| 板型 | 文件 | 初始化入口 | 触摸芯片 |
|------|------|------------|----------|
| **waveshare-s3-touch-lcd-3.5b** | `main/boards/waveshare-s3-touch-lcd-3.5b/waveshare-s3-touch-lcd-3.5b.cc` | `InitializeTouch()` | AXS15231B |
| **wireless-tag-wtp4c5mp07s** | `main/boards/wireless-tag-wtp4c5mp07s/wireless-tag-wtp4c5mp07s.cc` | `InitializeTouch()` | GT911 |
| **m5stack-tab5** | `main/boards/m5stack-tab5/m5stack_tab5.cc` | `InitializeSt7123TouchPad()` / `InitializeGt911TouchPad()` | ST7123 / GT911 |
| **esp32-s3-touch-lcd-3.5** | `main/boards/esp32-s3-touch-lcd-3.5/esp32-s3-touch-lcd-3.5.cc` | 板级 `InitializeTouch` | 对应 esp_lcd_touch |
| **stackchan 板型** | `main/boards/stackchan/stackchan_board.cc` | `InitializeFt6336TouchPad()` | FT6336 |
| **xingzhi-metal-1.54-wifi** | 自研 CST816x，非 LVGL | `Cst816x::InitCst816d()` → `touchpad_daemon` 任务 | CST816x |

**典型初始化流程（LVGL 板型）**：

```c
// 以 wireless-tag-wtp4c5mp07s.cc 为例
void InitializeTouch() {
    esp_lcd_touch_handle_t tp;
    esp_lcd_touch_config_t tp_cfg = { .x_max = DISPLAY_WIDTH, .y_max = DISPLAY_HEIGHT, ... };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c(...));
    ESP_ERROR_CHECK(esp_lcd_touch_new_i2c_gt911(..., &tp));
    const lvgl_port_touch_cfg_t touch_cfg = { .disp = lv_display_get_default(), .handle = tp };
    lvgl_port_add_touch(&touch_cfg);  // 将触摸接入 LVGL
}
```

### 2.2 stack-chan（Moddable TypeScript）

**文件**：`stack-chan/firmware/stackchan/main.ts`

**初始化**：

```ts
const TouchConstructor = config.Touch || globalEnv.device?.sensor?.Touch
const touch = TouchConstructor ? new Touch(TouchConstructor) : undefined
return new Robot({ driver, renderer, tts, button, touch, ... })
```

- 若 `config.Touch` 或 `device.sensor.Touch` 存在，则创建 `Touch` 实例并传入 `Robot`
- `Touch` 类定义于 `stack-chan/firmware/stackchan/touch.ts`

---

## 三、2. 触摸区域定义（Zones / Buttons）

### 3.1 有明确坐标区域的定义

**仅 xingzhi-metal-1.54-wifi 板型** 有显式坐标到功能的映射。

**文件**：`1.27-xiaozhi/main/boards/xingzhi-metal-1.54-wifi/cst816x.h`

```cpp
const std::array<TouchThresholdConfig, 3> TOUCH_THRESHOLD_TABLE = {
    {20, 600, ...},   // 音量+
    {40, 600, ...},   // boot 按键（主功能）
    {60, 600, ...}    // 音量-
};
```

- 底部 y≈600 区域被分为三个 X 坐标：20 / 40 / 60
- 每个区域有 `single_click_thresh_us`、`double_click_window_us`、`long_press_thresh_us` 等配置
- **区分逻辑**：通过 `(x, y)` 与 `TOUCH_THRESHOLD_TABLE` 的精确匹配（`getThresholdConfig(tp.x, tp.y)`）决定是音量+、boot 还是音量-

### 3.2 无区域划分的板型

**stackchan 板型**（`stackchan_board.cc`）：

- 使用 FT6336 轮询，**未做坐标分区**
- 任意有效触摸（`touch_point.num > 0`）在短按后统一触发 `app.ToggleChatState()` / 配网重置
- 不区分「摸脸」和「按键」：整屏视为同一功能

**waveshare / wireless-tag / m5stack-tab5 等 LVGL 板型**：

- 触摸通过 `lvgl_port_add_touch` 接入 LVGL
- 区域由 **LVGL 控件** 定义：`lv_btn`、`lv_label` 等的位置与 hit-test 决定
- 无类似 BtnA/BtnB/BtnC 或 Face 的全局区域常量，依赖 UI 布局

### 3.3 stack-chan Moddable 固件

- `Touch` 类提供 `onTouchBegan(x, y)`, `onTouchMoved`, `onTouchEnded`
- **默认 mod 未绑定这些回调**：`on-robot-created.ts` 只使用 `robot.button.a/b/c`（物理按键）
- 如需按坐标区分区域，需在 mod 中自行实现，例如：

```ts
robot.touch.onTouchBegan = (x, y) => {
  if (y < screenHeight / 2) {
    // 上半屏 ≈ 摸脸
  } else {
    // 下半屏 ≈ 按键区域
  }
}
```

---

## 四、3. 事件处理循环

### 4.1 1.27-xiaozhi

#### A. LVGL 板型（大部分触摸屏板型）

- **循环位置**：由 LVGL 内部 `lv_timer` 驱动，`lvgl_port` 负责调用 `esp_lcd_touch_read_data`
- **用户层**：通过 `lv_obj_add_event_cb(btn, callback, LV_EVENT_CLICKED, ...)` 等处理触摸
- **无显式 `loop()` 里的 `isPressed` 检查**，由 LVGL 控件与输入设备完成

#### B. xingzhi-metal（CST816x 自定义）

**文件**：`1.27-xiaozhi/main/boards/xingzhi-metal-1.54-wifi/cst816x.cc`

**循环**：`touchpad_daemon` 任务

```cpp
void Cst816x::touchpad_daemon(void* arg) {
    while (1) {
        cst816x->UpdateTouchPoint();
        auto& tp = cst816x->GetTouchPoint();
        // 状态机：tp.num > 0 / == 0，is_touching_，click_count_，long_press_started_
        // 检测 SINGLE_CLICK / DOUBLE_CLICK / LONG_PRESS_START / LONG_PRESS_END
        if (event_detected) {
            if (current_event.y == 600 && (x == 20 || x == 40 || x == 60)) {
                switch (current_event.type) {
                    case SINGLE_CLICK:
                        if (x == 40) app.ToggleChatState();  // boot
                        else if (x == 20) 音量+; else 音量-;
                        break;
                    // ...
                }
            }
        }
        vTaskDelay(pdMS_TO_TICKS(40));
    }
}
```

- 等效于在主循环中检测 `isPressed` / `wasPressed` / `wasClicked`，由自定义状态机完成

#### C. stackchan 板型（FT6336）

**文件**：`1.27-xiaozhi/main/boards/stackchan/stackchan_board.cc`

**循环**：`esp_timer` 定时回调 `PollTouchpad`，周期 20ms

```cpp
void PollTouchpad() {
    ft6336_->UpdateTouchPoint();
    auto& touch_point = ft6336_->GetTouchPoint();
    if (touch_point.num > 0 && !was_touched) { was_touched = true; touch_start_time = ...; }
    else if (touch_point.num == 0 && was_touched) {
        was_touched = false;
        if (touch_duration < TOUCH_THRESHOLD_MS) {  // 短按
            app.ToggleChatState();  // 或 ResetWifiConfiguration
        }
    }
}
```

### 4.2 stack-chan Moddable

**文件**：`stack-chan/firmware/stackchan/touch.ts`

- **ECMA-419 驱动**：`touch.sample()`，`Timer.repeat(onSample, 16)` 每 16ms 轮询
- **Legacy 驱动**：`touch.read(points)`，`Timer.repeat(..., 15)` 每 15ms 轮询
- 根据 `point.state`（0/1/2/3）触发 `onTouchBegan` / `onTouchMoved` / `onTouchEnded`
- **on-launch.ts** 中 `waitForKey()` 使用 `touch.sample()` 或 `touch.read()` 判断 `isPressed()`，用于启动时等待用户触摸

---

## 五、4. 回调与反馈

### 5.1 触摸 → 系统菜单 / 状态切换

| 板型 | 触摸反馈 |
|------|----------|
| **xingzhi-metal** | `app.ToggleChatState()`（x=40）、音量+/−、长按音量 |
| **stackchan** | `app.ToggleChatState()`、`ResetWifiConfiguration()`（启动且未联网时） |
| **LVGL 板型** | 由 LVGL 控件 `LV_EVENT_CLICKED` 等回调决定（如按钮、列表项） |

### 5.2 触摸 → Avatar 表情（setExpression）

**1.27-xiaozhi**：

- **屏幕触摸** 不直接调用 `setExpression`
- Avatar 表情由 **HeadPet（摸头）** 驱动，而非屏幕触摸
- HeadPet 流程：
  - 板级 HeadPet 驱动（如 Si12T 三区触摸）识别 Press/Release 等
  - 调用 `Application::OnHeadPetGesture(gesture)`
  - 转发到 `HeadPetModifier::TriggerHappy()` / `TriggerRelease()`
- 当前 HeadPet 为**桩实现**：`InitializeHeadPet()` 为空，见 `stackchan_board.cc` 注释

**stack-chan Moddable**：

- `robot.setEmotion()` / `robot.setColor()` 可改变表情与主题色
- 默认 `on-robot-created.ts` 中由 **物理按键** `button.a/b/c` 触发，与 `Touch` 无关
- 若 mod 中设置 `robot.touch.onTouchBegan`，可自行实现触摸→表情逻辑（如上半屏→摸脸效果）

### 5.3 总结：「摸脸」vs「按键」

| 概念 | 1.27-xiaozhi | stack-chan Moddable |
|------|--------------|---------------------|
| **摸脸** | HeadPet（机身头部三区触摸，Si12T）→ `HeadPetModifier`，当前为桩 | 无默认实现；可 mod 中用 `touch.onTouchBegan` 按坐标实现 |
| **按键** | 屏幕底部固定坐标（xingzhi）或整屏短按（stackchan 板型）；物理 BOOT 键 | 物理 `button.a/b/c`；屏幕触摸需 mod 自行绑定 |
| **区分方式** | xingzhi：`(x,y)` 精确匹配 20/40/60 @ y=600；stackchan 板型：不区分 | 需 mod 按 `(x,y)` 或区域划分实现 |

---

## 六、相关文件索引

| 类别 | 文件路径 |
|------|----------|
| **触摸初始化（LVGL）** | `waveshare-s3-touch-lcd-3.5b.cc`, `wireless-tag-wtp4c5mp07s.cc`, `esp32-s3-touch-lcd-3.5.cc`, `m5stack-tab5.cc` 等 |
| **触摸初始化（stackchan）** | `main/boards/stackchan/stackchan_board.cc` → `InitializeFt6336TouchPad` |
| **坐标区域定义** | `main/boards/xingzhi-metal-1.54-wifi/cst816x.h`（TOUCH_THRESHOLD_TABLE） |
| **事件处理循环（自定义）** | `main/boards/xingzhi-metal-1.54-wifi/cst816x.cc`（touchpad_daemon） |
| **事件处理循环（stackchan）** | `main/boards/stackchan/stackchan_board.cc`（PollTouchpad） |
| **Touch 类（Moddable）** | `stack-chan/firmware/stackchan/touch.ts` |
| **Mod 入口** | `stack-chan/firmware/stackchan/main.ts`, `default-mods/on-robot-created.ts` |
| **HeadPet（摸脸）** | `main/stackchan/modifiers/head_pet.h`, `main/application.h`（OnHeadPetGesture） |
| **LVGL 显示** | `main/display/lcd_display.cc`（lvgl_port） |

---

## 七、控制流简图

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1.27-xiaozhi (LVGL 板型)                                                │
├─────────────────────────────────────────────────────────────────────────┤
│ esp_lcd_touch_* / GT911/ST7123/... → lvgl_port_add_touch                 │
│       ↓                                                                 │
│ LVGL indev 轮询 → lv_indev_read → 控件 hit-test                         │
│       ↓                                                                 │
│ lv_obj 的 LV_EVENT_CLICKED 等 → 应用回调（按钮、菜单）                   │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ 1.27-xiaozhi (xingzhi-metal)                                            │
├─────────────────────────────────────────────────────────────────────────┤
│ CST816x touchpad_daemon 任务                                            │
│   UpdateTouchPoint → 状态机 → event_detected                            │
│   (x,y)==(20,600)→音量+  (40,600)→ToggleChatState  (60,600)→音量-       │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ 1.27-xiaozhi (stackchan 板型)                                           │
├─────────────────────────────────────────────────────────────────────────┤
│ FT6336 PollTouchpad (20ms) → 短按 → ToggleChatState / ResetWifiConfig    │
│ （无坐标分区，整屏等效）                                                 │
│ HeadPet：InitializeHeadPet() 为桩，待 Si12T 驱动接入                     │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ stack-chan Moddable                                                      │
├─────────────────────────────────────────────────────────────────────────┤
│ Touch 类 Timer.repeat(16ms) → sample/read → onTouchBegan/Moved/Ended    │
│ 默认 mod：仅 button.a/b/c → lookAt、testMotion、setColor                 │
│ touch 回调未被默认 mod 使用，需自定义 mod 按坐标分区                     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 八、后续改进建议

1. **stackchan 板型**：可仿照 xingzhi-metal 增加 `(x,y)` 分区（如上半屏=摸脸/表情，下半屏=功能键），并在上半屏触摸时调用 `HeadPetModifier::TriggerHappy()` 等。
2. **HeadPet 驱动**：在 `InitializeHeadPet()` 中接入 Si12T，识别 Press/Release/Swipe 后调用 `OnHeadPetGesture` 和 `HeadPetModifier::TriggerHappy/TriggerRelease`。
3. **stack-chan mod**：在 `onRobotCreated` 中为 `robot.touch` 设置 `onTouchBegan`，按 `(x,y)` 划分 Face / BtnA/BtnB/BtnC 等区域并触发对应逻辑。
