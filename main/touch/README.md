# TouchManager 触摸管理模块

为 ESP32-S3-BOX-3B (GT911) 提供归一化坐标、去抖动与视线平滑，适用于眼睛跟手等交互。

## 功能

- **驱动**：esp_lcd_touch_gt911
- **归一化**：物理坐标 → 0.0~1.0 浮点，换屏无需改逻辑
- **线程安全**：独立任务采样，信号量保护
- **去抖动**：30ms 稳定后更新
- **视线平滑**：指数移动平均，用于眼睛跟手

## 输出接口

```c
typedef struct {
    bool touched;       // 是否被触摸
    float x, y;        // 归一化 [0,1]
    uint16_t pressure; // 触摸压力
} TouchPoint;

typedef struct {
    float gaze_x, gaze_y;  // 平滑视线 [0,1]，未触摸时回 0.5
} GazePoint;
```

## 使用示例

```cpp
#include "touch/touch_manager.h"
#include "config.h"

touch::TouchManager tm;
touch::TouchManagerConfig cfg = {
    .sda = TOUCH_I2C_SDA_PIN,   // 8
    .scl = TOUCH_I2C_SCL_PIN,   // 18
    .int_pin = TOUCH_INT_PIN,   // 3
    .rst_pin = TOUCH_RST_PIN,   // 48
    .display_width = DISPLAY_WIDTH,
    .display_height = DISPLAY_HEIGHT,
    .swap_xy = DISPLAY_SWAP_XY,
    .mirror_x = DISPLAY_MIRROR_X,
    .mirror_y = DISPLAY_MIRROR_Y,
};
tm.Init(cfg, i2c_bus);  // 传入已有 I2C 总线可复用

TouchPoint pt;
tm.GetState(&pt);
if (pt.touched) {
    // pt.x, pt.y 为 0~1
}

GazePoint gaze;
tm.GetGazePoint(&gaze);
// gaze.gaze_x, gaze.gaze_y 用于眼睛跟手
```

## GT911 硬件检查（I2C NACK 时）

若出现 `esp_lcd_touch_new_i2c_gt911 failed: ESP_ERR_INVALID_STATE` 或 `I2C transaction unexpected nack detected`，按以下步骤排查：

### 1. 确认触摸屏型号
- 查看屏幕背面/规格书，是否为 **GT911** 触摸芯片
- ESP-BOX-3 原装配件一般为 GT911；第三方屏可能是 CST816、FT6236 等，需更换驱动

### 2. 核对引脚接线
当前 `config.h` 配置（BOX-3B）：
| 信号 | GPIO | 说明 |
|------|------|------|
| SDA  | 8    | I2C 数据 |
| SCL  | 18   | I2C 时钟 |
| INT  | 3    | 触摸中断 |
| RST  | 48   | 复位（可能与 LCD 共用） |

- 用万用表确认屏幕 FPC/排线对应的 SDA/SCL/INT/RST 是否接到上述 GPIO
- 若板子丝印或原理图不同，需修改 `boards/esp-box-3/config.h`

### 3. I2C 地址
- GT911 地址由 INT 引脚在上电复位时电平决定：高→0x14，低→0x5D
- **BOX-3B 固定使用 0x5D**，不轮询地址，避免 0x14 的 NACK 误报
- 若仍 NACK，可用 **I2C 扫描** 验证：烧录 `idf.py -p COMx run` 前，临时加 I2C 扫描代码，查看 0x14/0x5D 是否有响应

### 4. 电源与复位
- 触摸与 LCD 共用供电时，确认 3.3V 稳定
- RST 与 LCD 共用 GPIO 48 时，LCD 初始化会拉一次复位，GT911 会随之复位；若未共用，需确认 RST 有正确复位序列
- 代码已在初始化前增加约 100ms 延时，便于 GT911 上电就绪

### 5. 总线冲突
- GT911 与 ES8311/ES7210 共用 I2C 总线（SDA:8, SCL:18）
- 确认总线上无短路、上拉电阻正常（通常 4.7kΩ）
- 可尝试降低 I2C 速度（touch_manager 中 `tp_io_config.scl_speed_hz` 改为 100000）

### 6. 冷启动 vs 重启（为何配网后 I2C 就正常？）
- **现象**：首次上电（冷启动）时 GT911 常 NACK，配网成功重启后恢复正常
- **原因**：冷启时整机供电、LCD 复位、I2C 总线时序尚未完全稳定；`esp_restart()` 为软重启，外设未掉电，GT911 已处于就绪状态
- **处理**：初始化前延时已增至 300ms；若仍偶发 NACK，可尝试 500ms 或检查电源质量

---

## 配置 (config.h)

BOX-3B 引脚已在 `boards/esp-box-3/config.h` 中预留：

- TOUCH_I2C_SDA_PIN = 8
- TOUCH_I2C_SCL_PIN = 18
- TOUCH_INT_PIN = 3
- TOUCH_RST_PIN = 48

## GestureEngine 手势识别

基于 TouchManager 归一化坐标的异步手势引擎，由 esp-box-3 板型自动启动（~30Hz 定时更新）。

### 区域划分

- **FaceZone** (y < 0.8)：头部 y < 0.4，脸部 0.4 ≤ y < 0.8
- **Bottom** (y ≥ 0.8)：底部区域

### 识别手势

| 手势 | 说明 |
|------|------|
| TAP | 单击，短按释放 |
| DOUBLE_TAP | 双击，用于唤醒 |
| LONG_PRESS | 长按 > 800ms |
| SWIPE_LEFT/RIGHT/UP/DOWN | 滑动 |
| CIRCLE | FaceZone 内画圈 |

### 使用示例

```cpp
#include "touch/gesture_engine.h"
#include "boards/common/board.h"

auto* ge = Board::GetInstance().GetGestureEngine();
if (ge) {
    ge->SetCallback([](const GestureEvent& e) {
        if (e.type == GESTURE_DOUBLE_TAP) { /* 唤醒 */ }
        if (e.type == GESTURE_CIRCLE && e.zone == GESTURE_ZONE_FACE) { /* 摸脸开心 */ }
    });
}
// 或轮询
GestureEvent ev;
if (ge->PollGesture(&ev)) { /* 处理 ev */ }
```

## GestureHandler 手势→行为映射

esp-box-3 启动时自动注册 GestureHandler，将手势映射到表情、语音、系统功能。

### 摸脸互动 (HeadPet)

| 手势 | 区域 | 行为 |
|------|------|------|
| TAP | 头部 (y&lt;0.4) | Happy 表情 + 气球「好舒服~」 |
| LONG_PRESS | 脸部 (0.4≤y&lt;0.8) | Shy 表情 + 异步害羞语音（占位） |
| SWIPE_LEFT/RIGHT | FaceZone | Angry/Dizzy 随机 + 气球「别揉啦」+ 音效 |
| LONG_PRESS | 头部 | Sleepy 表情 + 低功耗休眠 |

### 系统与滑动

| 手势 | 行为 |
|------|------|
| SWIPE_LEFT/RIGHT | 底部区域：切换 light/dark 主题 |
| SWIPE_UP/DOWN | 调节音量 + 短暂显示音量条 |
| DOUBLE_TAP | 唤醒 + Happy + 打招呼音效 |
| CIRCLE | FaceZone：DanceModifier 庆祝动画 |

### 视线跟随

手指在 FaceZone 内移动且未触发手势时，TouchGazeModifier 驱动眼睛平滑跟随 (`avatar.leftEye/rightEye.setPosition`)。

### 异步与反馈

- 表情、气球、音量条：`Application::Schedule()` 主循环执行
- 语音播放：独立 Task + 队列，不阻塞触摸与 Avatar 动画

---

## 迁移至 LovyanGFX

若未来使用 LGFX 驱动显示，可将 TouchManager 内部数据源改为 `LGFX::getTouch()`，对外接口保持不变。
