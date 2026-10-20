# ESP-BOX-3 触摸屏与白屏问题分析

## 一、现象描述

- **加触摸屏之前**：表情显示正常
- **加触摸屏之后**：出现白屏

## 二、核心发现：LCD 与触摸共用复位引脚

### 2.1 引脚配置

| 模块 | 复位引脚 | 配置位置 |
|------|----------|----------|
| **LCD (ILI9341/ILI9342)** | GPIO 48 | `esp_box3_board.cc` → `panel_config.reset_gpio_num` |
| **触摸 (GT911)** | GPIO 48 | `config.h` → `TOUCH_RST_PIN` |

两个模块都使用 **GPIO 48** 作为复位引脚。

### 2.2 初始化顺序

```
1. InitializeI2c()
2. InitializeSpi()
3. InitializeIli9341Display()   ← LCD 初始化、GPIO48 复位、显示开启
4. vTaskDelay(1500)
5. InitializeTouch()           ← GT911 初始化，对 GPIO48 再次做复位序列
```

### 2.3 问题机制

`esp_lcd_touch_new_i2c_gt911()` 内部会对 `rst_gpio_num`（即 GPIO 48）做复位：
拉低 → 延时 → 拉高。

由于 LCD 与触摸共用 GPIO 48，**触摸初始化时对 GPIO 48 的复位，会同时把已经初始化并正常显示的 LCD 再次复位**，使其回到上电默认状态，表现为白屏。

### 2.4 佐证

- `touch_manager.h` 注释：`GPIO_NUM_NC 表示共用 LCD RST`，说明 LCD 与触摸 RST 在硬件上可能共用
- 无触摸时正常、加触摸后白屏，与“触摸初始化再次复位 LCD”的时序一致

## 三、可能原因总结

| 可能性 | 说明 |
|--------|------|
| **共用 RST 导致二次复位** | 触摸初始化时对 GPIO 48 的复位同时复位 LCD，最符合现象 |
| I2C 共用 | 触摸与音频编解码器共用 I2C，通常不会直接导致白屏 |
| 冷启 I2C NACK | 说明 GT911 上电时序或总线有问题，但与白屏不一定直接相关 |

## 四、问题本质确认

**是的，问题在于复位引脚的复用**。LCD 与触摸共用 GPIO 48，触摸初始化时的复位操作把已工作的 LCD 再次复位，导致白屏。

---

## 五、市面常见做法及可选方案

### 5.1 行业常见做法

| 做法 | 适用场景 | 说明 |
|------|----------|------|
| **一次复位，分步配置** | 显示+触摸一体模组 | 上电或启动时对共用 RST 做一次复位，随后只通过 SPI/I2C 分别配置 LCD 和触摸，**触摸驱动不再拉 RST** |
| **触摸不接 RST（GPIO_NUM_NC）** | 共用 RST 的模组 | 触摸芯片 RST 在硬件上与 LCD 连在同一引脚，软件只给 LCD 做复位；触摸驱动使用 `rst_gpio_num = -1` 或 `GPIO_NUM_NC`，跳过独立复位 |
| **先复位再初始化** | 共用 RST | 在初始化 LCD 之前对 GPIO 48 做一次复位（LCD+触摸同时复位），然后 LCD init → 显示 → 触摸 init（触摸 init 不再操作 RST） |
| **分线设计** | 新硬件 | LCD 和触摸各自使用独立 RST 引脚，互不影响，成本略高 |
| **触摸复位后重做 LCD 初始化** | 必须单独复位触摸时 | 触摸 init 做完复位后，再执行一次 LCD 初始化，恢复显示 |

### 5.2 针对 ESP-BOX-3 的可选方案

| 方案 | 实现难度 | 改动范围 | 说明 |
|------|----------|----------|------|
| **A. 触摸 RST 设为 GPIO_NUM_NC** | ★ 低 | `config.h` | `TOUCH_RST_PIN` 改为 `GPIO_NUM_NC`，touch_manager 会将 `config_.rst_pin` 传给 GT911 驱动。esp_lcd_touch_gt911 支持 `rst_gpio_num = -1` 跳过复位。LCD 复位时已同时复位触摸，触摸 init 不再拉 RST。**优先推荐** |
| **B. 调整初始化顺序** | ★★ 中 | `esp_box3_board.cc` | 在 LCD init 之前对 GPIO 48 做一次复位；或先 init 触摸（含复位），再 init LCD。需确认 GT911 在 LCD init 之前完成复位、LCD init 在后不会影响触摸。 |
| **C. 触摸 init 后重做 LCD 初始化** | ★★ 中 | `esp_box3_board.cc` | 保持现有顺序，在 `InitializeTouch()` 之后再次调用 LCD 的 reset + init，恢复显示。实现简单，但有重复初始化开销。 |
| **D. 触摸改为后台延迟初始化** | ★★★ 高 | `esp_box3_board.cc` | 显示稳定后再启动触摸 init 任务，触摸 init 时传入 `GPIO_NUM_NC` 不做复位。可配合方案 A 使用。 |
| **E. 查阅并跟随官方实现** | ★ 低 | 参考用 | 查看 esp-box 仓库中 ESP32-S3-BOX-3 的官方例程，确认其 RST 配置和初始化顺序，再决定采用上述哪种方案。 |

### 5.3 方案 A 的技术依据

- esp_lcd_touch_gt911 支持 `rst_gpio_num = -1` 或 `GPIO_NUM_NC` 表示“不使用复位引脚”
- LCD 与触摸共用 RST 时，LCD 复位已经对触摸做了上电/复位，触摸只需 I2C 配置
- GT911 INT 引脚需正确连接，用于 I2C 地址选择；与 RST 是否使用无关

### 5.4 实现注意事项

- 若采用 **方案 A**：`touch_manager.cc` 已将 `config_.rst_pin` 直接传给 `rst_gpio_num`，故仅需在 `config.h` 中把 `TOUCH_RST_PIN` 改为 `GPIO_NUM_NC`
- 若采用 **方案 B**：需对照 GT911 数据手册的复位时序，保证 LCD 初始化不会干扰触摸状态
- 若采用 **方案 C**：重做 LCD init 后，可能需重新设置显示内容（如表情等）

---

## 六、关于恢复代码后的编译错误

恢复 `image_to_jpeg.h` 后出现 `V4L2_PIX_FMT_RGB565` / `image_to_jpeg_cb` 未声明，原因是：

- 原始头文件使用 `#ifndef CONFIG_IDF_TARGET_ESP32`
- 在 ESP32-S3 构建时，Kconfig 会把未选中的 `CONFIG_IDF_TARGET_ESP32` 定义为 0（宏仍存在）
- `#ifndef` 只判断“是否未定义”，宏存在即会排除整段 API，导致 `image_to_jpeg_cb` 和 `V4L2_PIX_FMT_RGB565` 未被声明

因此恢复“原始”写法后，ESP32-S3 无法通过编译。之前仅修改条件判断（而非删除或大改逻辑）的修正，是面向 ESP32-S3 正确编译所必需的。

---

## 七、相关文件

- `main/boards/esp-box-3/config.h` — 引脚定义
- `main/boards/esp-box-3/esp_box3_board.cc` — 初始化顺序
- `main/touch/touch_manager.cc` — GT911 初始化
- `main/touch/touch_manager.h` — 配置与 RST 共用说明
