# ESP32-S3-BOX-3 触摸“点击/滑动无效”深度排查报告

> 说明：小智项目在 esp-box-3 上 **不采用 LVGL 触摸输入**，因此您提到的 `lv_indev`、`LV_EVENT_GESTURE`、`LV_OBJ_FLAG_GESTURE_BUBBLE` 等在此板型上均不适用。排查需聚焦 **TouchManager → GestureEngine → GestureHandler** 链路。

---

## 一、架构概览

### 1.1 实际触摸链路（esp-box-3）

```
GT911 硬件
    ↓ esp_lcd_touch_read_data / esp_lcd_touch_get_data
TouchManager (TaskLoop, 10ms 轮询)
    ↓ GetState() 输出归一化坐标
GestureEngine (esp_timer 33ms 回调)
    ↓ 状态机 IDLE → PRESSED → MOVING，识别 TAP/SWIPE/LONG_PRESS
GestureHandler (OnGesture 回调)
    ↓ SetEmotion / SetChatMessage / 音量等
```

### 1.2 LVGL 与本项目的关系

| 您提到的 LVGL 概念 | 在 esp-box-3 上的情况 |
|-------------------|------------------------|
| `lv_port_indev.c` / `lv_indev_drv_register` | **无**：esp-box-3 未将触摸接入 LVGL |
| `LV_EVENT_GESTURE` | **无**：手势由自研 GestureEngine 处理 |
| `LV_OBJ_FLAG_GESTURE_BUBBLE` | **无**：当前 UI 为 EmoteDisplay（程序化表情），非 LVGL 控件树 |
| `LV_INDEV_DEF_READ_PERIOD` | **不适用** |
| `LV_GESTURE_LIMIT` | **不适用** |

---

## 二、关键文件定位

| 模块 | 文件 | 作用 |
|------|------|------|
| 触摸采样 | `main/touch/touch_manager.cc` | `TaskLoop()` 每 10ms 调用 `esp_lcd_touch_read_data` + `esp_lcd_touch_get_data`，更新 `state_.touched / x / y` |
| 手势识别 | `main/touch/gesture_engine.cc` | `Update()` 每 33ms 被 esp_timer 调用，状态机输出 TAP/SWIPE 等 |
| 手势处理 | `main/touch/gesture_handler.cc` | `OnGesture()` 接收事件，执行表情切换、音量调节等 |
| 板级接入 | `main/boards/esp-box-3/esp_box3_board.cc` | `InitializeTouch()` 创建 TouchManager、GestureEngine、GestureHandler 并注册回调 |

---

## 三、滑动识别逻辑（GestureEngine）

### 3.1 状态转换条件

```
IDLE → PRESSED：pt.touched == true
PRESSED → MOVING：|pt.x - down_x| > 0.08 或 |pt.y - down_y| > 0.08
MOVING → IDLE：pt.touched == false（手指抬起）
```

### 3.2 滑动判定（在 TouchUp 时）

```cpp
// gesture_engine.cc OnTouchUp()
if (state_ == MOVING && (max_dx_ >= kSwipeMinDist || max_dy_ >= kSwipeMinDist)) {
    // 发出 SWIPE_LEFT/RIGHT/UP/DOWN
}
```

**关键常量**：
- `kTapMaxMove = 0.08`：位移超过屏幕 8% 才进入 MOVING
- `kSwipeMinDist = 0.2`：位移超过屏幕 20% 才识别为滑动  
  - 在 320×240 下：水平约 64px，竖直约 48px

---

## 四、“点击有效、滑动无效”的可能原因

### 4.1 触摸数据在滑动过程中中断（优先怀疑）

**现象**：滑动时某几帧 `GetState()` 返回 `touched = false`。

**后果**：  
- 在 PRESSED 或 MOVING 时收到 `touched = false`，会立刻 `OnTouchUp()` 并回到 IDLE  
- 若还未进入 MOVING，或 `max_dx_`/`max_dy_` 未达 0.2，则不会发出 SWIPE，只会当作异常短按或无法识别

**可能来源**：
1. **I2C 总线冲突**：触摸与 ES8311/ES7210 共用 I2C，音频密集访问时，触摸读取可能失败或超时，`esp_lcd_touch_get_data` 返回 `cnt = 0`，被当作“未触摸”
2. **GT911 采样**：若读得太慢或漏读，芯片内部缓冲溢出，也会出现断续
3. **任务调度**：TouchManager 任务被延迟时，轮询间隔变大，可能漏掉中间点

### 4.2 刷新率与采样率不足

- GestureEngine：33ms 一次（约 30Hz）
- TouchManager：10ms 一次（100Hz）

一次约 300ms 的滑动，理论上约 9 次 GestureEngine 采样；要满足 20% 位移（约 48px），每次平均需约 5px。速度略快时，若再叠加 I2C 丢点，可能难以达到 `kSwipeMinDist`。

### 4.3 滑动距离或习惯不匹配

- 需移动 **至少约 48px（竖向）或 64px（横向）** 才能识别为滑动  
- 若习惯短距离滑动，易被判为 TAP 或无法识别

---

## 五、诊断建议（先讨论，暂不修改）

### 5.1 增加触摸调试日志（确认底层是否有连续点）

**位置**：`main/touch/touch_manager.cc` 的 `UpdateState()`

当前已有 touch down/up 日志；可增加：

- 在 `touched == true` 时，每隔 N 次采样打印一次 `(raw_x, raw_y)`，观察滑动过程中坐标是否连续
- 注意：高频打印会影响性能，建议加采样率限制（如每 50ms 打一次）

### 5.2 增加手势引擎调试日志（确认状态与位移）

**位置**：`main/touch/gesture_engine.cc` 的 `OnTouchUp()`

- 在 `OnTouchUp` 中打印：`state_`、`max_dx_`、`max_dy_`、`duration_ms`
- 可区分：
  - 从未进入 MOVING（位移一直 < 8%）
  - 进入 MOVING 但 `max_dx_`/`max_dy_` < 0.2（位移不足 20%）
  - 中途因 `touched = false` 提前结束

### 5.3 临时测试用代码（用于验证滑动路径）

在 `GestureEngine::OnTouchMove()` 中，可增加“每 5 次调用打印一次 `(x, y)`”的调试，以确认：

- 滑动时是否持续进入 `OnTouchMove`
- 坐标变化是否连贯

---

## 六、与 LVGL 的对比小结

| 项目 | LVGL 方案 | 小智 esp-box-3 方案 |
|------|-----------|----------------------|
| 输入源 | `lv_indev` read 回调 | TouchManager `GetState()` |
| 手势识别 | LVGL 内部手势 | 自研 GestureEngine 状态机 |
| 事件 | `LV_EVENT_GESTURE` | `GestureEvent` 结构体 + `OnGesture` 回调 |
| 控件 | LVGL 树 + hit-test | EmoteDisplay 程序化表情，无控件树 |

因此，排查应集中在 **TouchManager 数据连续性** 和 **GestureEngine 状态与阈值**，而不是 LVGL 的 indev / 手势配置。

---

## 七、为什么“点击、滑动都无效”？

当**点击和滑动都不工作**时，问题多半出在链路最前端：

### 7.1 最可能原因：TouchManager 无有效触摸数据

| 环节 | 现象 | 排查方向 |
|------|------|----------|
| **GT911 初始化失败** | `touch_manager_.Init()` 返回 false，`InitializeTouch()` 不创建手势定时器 | 检查串口是否有 `GT911 init OK` 日志；若没有，说明 I2C 或地址 0x5D 异常 |
| **始终 cnt=0** | `esp_lcd_touch_get_data` 一直返回无点 | I2C 冲突、GT911 未复位、接线/引脚错误、部分板子需 0x14 |
| **GetState 互斥超时** | `xSemaphoreTake` 超时返回 false | GestureEngine 拿到的是默认 `touched=false`，相当于从未按下 |

### 7.2 次要可能

- **TOUCH_I2C_SDA_PIN 未定义**：若 `config.h` 未定义，`InitializeTouch()` 被 `#ifdef` 完全跳过，触摸不会初始化  
- **I2C 总线共享**：触摸与 ES8311/ES7210 共用 SDA=8、SCL=18，音频密集访问时可能影响触摸读取  
- **RST 配置**：`TOUCH_RST_PIN = GPIO_NUM_NC`，依赖 LCD 的 `panel_reset` 同时复位 GT911；若 LCD 未先复位或顺序错误，GT911 可能异常

---

## 八、测试代码建议位置（仅讨论，不实际修改）

用于打印触摸坐标与手势方向，便于定位问题。

### 8.1 触摸连续性：`main/touch/touch_manager.cc`

**位置**：`UpdateState()` 中，在现有 down/up 日志之后。

- **内容**：当 `touched == true` 时，按时间节流（如每 50ms）打印一次 `(raw_x, raw_y)`，观察滑动时坐标是否连续  
- **目的**：确认 GT911 是否持续上报，以及 I2C 是否在滑动中丢点

### 8.2 手势状态与位移：`main/touch/gesture_engine.cc`

**位置**：`OnTouchUp()` 开头（在 `int64_t duration_ms = ...` 之后）。

- **内容**：打印 `state_`、`max_dx_`、`max_dy_`、`duration_ms`  
- **目的**：区分  
  - 未进入 MOVING（位移 < 8%）  
  - 进入 MOVING 但 `max_dx_`/`max_dy_` < 0.2（位移不足 20%）  
  - 中途因 `touched=false` 提前结束

### 8.3 手势方向与坐标：`main/touch/gesture_handler.cc`

**位置**：`OnGesture()` 开头（已有 `ESP_LOGI` 处）。

- **现状**：已有 `[Gesture] OnGesture %s zone=%s`  
- **可选**：增加 `(x, y)` 打印，便于核对手势与区域

---

## 九、建议的下一步讨论

1. **确认 TouchManager 是否工作**：烧录后触摸屏幕，观察串口是否有 `[Touch] DOWN`、`[Touch] UP`；若无，说明 GT911 或 I2C 有问题，与 LVGL 无关。  
2. **若有 DOWN/UP 但无 [Gesture] EMIT**：在 `OnTouchUp` 加 8.2 的调试，抓 `state_`、`max_dx_`、`max_dy_`，判断是否进入 MOVING 及位移是否达标。  
3. **若有 EMIT 但无视觉反馈**：检查 GestureHandler 的 `ScheduleVisual`、EmoteDisplay 的 `SetEmotion` 是否正常执行。  
4. **验证 I2C 冲突**：在滑动时暂停或减少音频 I2C 访问，观察识别是否改善。  
5. **参数调节**：若确认数据连续且位移不足，可考虑将 `kSwipeMinDist` 从 0.2 调至 0.15 做体验测试。

确定方向后，再在具体文件和行号上做最小改动。
