# ESP-BOX-3 (ILI9342C + GT911) 深度代码审查与补丁

## 一、硬件规格确认

- **LCD**: ILI9342C（与 ILI9341 寄存器兼容，可用 esp_lcd_ili9341 驱动）
- **触摸**: GT911
- **现象**: 白屏（有背光）、OnFlush 有输出、GT911 I2C NACK

---

## 二、审查结论

### 2.1 LCD 初始化（esp_box3_board.cc）

| 项目 | 当前值 | 说明 |
|------|--------|------|
| 驱动 | `esp_lcd_new_panel_ili9341` | 正确，ILI9342C 与 ILI9341 兼容 |
| vendor_config | 与 esp-box / esp-box-lite 相同 | 标准 gamma/电源序列，适用于 ILI9341/2 |
| SPI 频率 | 40MHz | 可尝试降为 20MHz 排查信号完整性 |
| SPI 模式 | 0 | 常见配置 |
| reset_active_high | 0 | 正确（低电平复位） |
| 500ms 延时 | 有 | 在 `esp_lcd_panel_reset` 前 |

### 2.2 白屏根因：GPIO 48 二次复位

**结论**：触摸初始化时 GT911 驱动对 GPIO 48 做复位，导致已工作的 LCD 被再次复位，回到上电默认状态（白屏）。

**时序**：
```
1. LCD init: esp_lcd_panel_reset(GPIO48 低→高) → LCD 初始化完成
2. 1.5s 延时
3. 板级: GPIO48 拉高，50ms
4. Touch init: esp_lcd_touch_new_i2c_gt911 内部对 rst_gpio_num(GPIO48) 做 低→延时→高
   → LCD 被再次复位！显示丢失
5. 触摸 I2C → NACK，触摸 init 失败
```

**修复**：将 `TOUCH_RST_PIN` 设为 `GPIO_NUM_NC`，触摸不再操作 RST。LCD 复位时已同时复位触摸芯片。

### 2.3 I2C 配置（GT911）

| 项目 | 当前值 | 说明 |
|------|--------|------|
| SDA | GPIO 8 | 与音频 codec 共用 |
| SCL | GPIO 18 | 与音频 codec 共用 |
| 地址 | 0x14 / 0x5D 依次尝试 | 正确，由 INT 在 RST 释放时电平决定 |
| 频率 | 100kHz | 已降低，利于排查 |
| INT | GPIO 3 | - |
| RST | GPIO 48（与 LCD 共用） | 应改为 NC |

### 2.4 初始化顺序与 GPIO 48

- LCD 在 `InitializeIli9341Display` 中使用 `panel_config.reset_gpio_num = GPIO_NUM_48`
- 触摸在 `config.rst_pin = TOUCH_RST_PIN` (GPIO48) 传入 TouchManager
- 板级在触摸 init 前对 GPIO 48 拉高，但触摸 init 内部仍会执行一次复位，导致 LCD 被复位

---

## 三、补丁清单

### 补丁 1：触摸 RST 改为 GPIO_NUM_NC（解决白屏）

**文件**: `main/boards/esp-box-3/config.h`

```c
#define TOUCH_RST_PIN       GPIO_NUM_NC  /* 与 LCD 共用 GPIO48，避免二次复位导致白屏 */
#define TOUCH_RST_IS_NC     1            /* 1=不单独复位触摸，依赖 LCD 复位 */
```

### 补丁 2：SPI 频率降为 20MHz（排查信号）

**文件**: `main/boards/esp-box-3/esp_box3_board.cc`

将 `io_config.pclk_hz = 40 * 1000 * 1000` 改为 `20 * 1000 * 1000`。

### 补丁 3：触摸 RST=NC 时跳过板级 GPIO 48 操作

在 `config.h` 增加 `TOUCH_RST_IS_NC 1`，板级使用 `#if !TOUCH_RST_IS_NC` 跳过对 RST 的拉高操作。

---

## 四、ILI9342C 初始化序列说明

当前 `vendor_specific_init` 与 esp-box / esp-box-lite 一致，包含：
- C8/C0/C5/C1/B4：电源、VCOM
- E0/E1：Gamma
- B1/36/3A/B7：时序、格式
- 11：Sleep Out
- 29：Display On

ILI9342C 与 ILI9341 寄存器兼容，无需额外修改。若 20MHz 后仍白屏，可参考 ILI9342 数据手册核对 0x36(MAC)、0x3A(Pixel Format) 等。

---

## 五、修改后建议验证顺序

1. 应用补丁 1（RST=NC）→ 重点验证白屏是否消失
2. 若仍白屏，应用补丁 2（SPI 20MHz）
3. 触摸 I2C NACK：在 RST=NC 后，GT911 依赖 LCD 复位时的 RST 释放，地址由当时 INT 电平决定；若持续 NACK，需查硬件（SDA/SCL/INT 连接、上拉、干扰）
