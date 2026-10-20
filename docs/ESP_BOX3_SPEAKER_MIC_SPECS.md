# ESP32-S3-BOX-3 喇叭与麦克风硬件规格分析

本文档基于当前工程代码分析 ESP32-S3-BOX-3 的**喇叭（Speaker）**和**麦克风（Microphone）**相关硬件与驱动配置，用于选购替换件时参考。

---

## 一、BSP/硬件定义位置说明

本工程**未使用** `components/bsp` 或 `managed_components` 下的独立 BSP 包，板级配置均在 **main** 下：

| 类型 | 路径 | 说明 |
|------|------|------|
| 板级引脚与音频宏 | `main/boards/esp-box-3/config.h` | AUDIO_*、CODEC、PA 等定义 |
| 板级初始化与 Codec 创建 | `main/boards/esp-box-3/esp_box3_board.cc` | 创建 BoxAudioCodec，传入 PA 引脚与 Codec 地址 |
| 音频 Codec 驱动 | `main/audio/codecs/box_audio_codec.cc` | ES8311 + ES7210 + PA 使能 |
| 通用 Codec 组件 | 依赖 `espressif/esp_codec_dev`（idf_component.yml） | ES8311/ES7210 驱动实现 |

---

## 二、喇叭（Speaker）链路与规格推断

### 2.1 代码中的驱动与芯片

| 角色 | 芯片/模块 | 代码位置 | 说明 |
|------|-----------|----------|------|
| 音频 DAC（数模转换） | **ES8311** | `box_audio_codec.cc` L40–50 | 仅 DAC 模式 `ESP_CODEC_DEV_WORK_MODE_DAC`，I2C 控制、I2S 输入 |
| 功放使能 | **GPIO 46**（PA 使能） | `config.h` → `AUDIO_CODEC_PA_PIN`，`box_audio_codec.cc` L46 | 仅作使能，不区分具体 PA 型号 |
| 实际功放芯片 (PA) | **未在代码中体现** | — | 原理图上在 ES8311 与喇叭之间，本仓库未包含型号 |

代码中与喇叭相关的关键配置（`box_audio_codec.cc`）：

```c
es8311_cfg.pa_pin = pa_pin;                    // GPIO 46
es8311_cfg.hw_gain.pa_voltage = 5.0;           // PA 供电/增益计算参考 5V
es8311_cfg.hw_gain.codec_dac_voltage = 3.3;    // Codec 输出参考 3.3V
```

含义简要说明：

- **ES8311**：只做 DAC，输出线/耳机电平，不直接驱动喇叭。
- **pa_pin**：控制外部功放的使能（开/关），不体现 PA 型号。
- **pa_voltage = 5.0**：用于软件侧增益/电平计算，常对应“功放供电约 5V”的典型设计；实际 PA 供电以原理图为准。
- **codec_dac_voltage = 3.3**：ES8311 模拟部分参考电压 3.3V。

### 2.2 功放 (PA) 型号

- 本仓库**没有任何** PA 型号（如 NS4168、AW88298、ES8156 等）的配置或驱动。
- PA 在硬件上接在 ES8311 输出与喇叭之间，由 GPIO 46 使能；具体型号需查阅**乐鑫官方 ESP32-S3-BOX-3 原理图/硬件说明**。

### 2.3 喇叭阻抗与功率建议（基于常见设计）

- **阻抗**：ES8311 不直接接喇叭，阻抗由**外部 PA** 决定。乐鑫类似板型（带 ES8311 + 外置 PA）常见为 **4Ω** 喇叭，少数为 8Ω。
- **功率**：代码无法给出具体瓦数；典型 1–3W 小喇叭在 5V 供电的 D 类 PA 下很常见，**1W–2W 为常见安全选型**。

**建议**：

1. **优先**查看乐鑫官方 ESP32-S3-BOX-3 的规格书/原理图，确认 PA 型号及推荐喇叭阻抗与功率。
2. 若无法获取官方资料，替换喇叭可先按 **4Ω、1W–2W** 试配；若板子标注或原装喇叭为 8Ω，则按 8Ω 选型。
3. 功率不宜明显大于原装（避免 PA 过载或失真）。

---

## 三、麦克风（Microphone）链路与规格

### 3.1 代码中的驱动与芯片

| 角色 | 芯片/模块 | 代码位置 | 说明 |
|------|-----------|----------|------|
| 麦克风 ADC | **ES7210** | `box_audio_codec.cc` L64–72 | 4 通道 ADC，I2C 控制，I2S TDM 输出到 ESP32 |
| 通道使用 | MIC1～MIC4 均使能 | `ES7210_SEL_MIC1 \| MIC2 \| MIC3 \| MIC4` | 双麦方案时多为 MIC1+MIC2（主麦+参考麦） |
| 采样率 | 24 kHz | `config.h` → `AUDIO_INPUT_SAMPLE_RATE` | 与 AEC 等算法匹配 |

要点：

- 麦克风**不是**接 ESP32 内部 ADC，而是接到 **ES7210** 的模拟输入。
- ES7210 提供 **MICBIAS** 输出，可给**模拟麦克风**（MEMS 或驻极体）供电。
- 数据经 ES7210 转为数字后，通过 **I2S TDM** 送给 ESP32，因此需使用**模拟麦**，不能是 I2S 数字麦模块。

### 3.2 麦克风类型与选型

- **类型**：需为**模拟麦克风**（Analog Microphone）。
  - **MEMS 硅麦**：需与 ES7210 的 MICBIAS 电压、输入阻抗匹配（数据手册一般写 1.8V/2.5V 等）。
  - **驻极体麦 (ECM)**：同样需板子提供偏置（ES7210 的 MICBIAS 常即为此用）。
- **接口**：信号接 ES7210 的 **MICxP/MICxN** 差分输入（或单端接法以原理图为准），**不是** I2S 数据线。
- 板子丝印 “AMIC” 与上述“模拟麦 + ES7210”一致。

**替换建议**：

- 使用与**原装规格一致**的模拟麦（MEMS 或驻极体，视原板设计）。
- 关键参数需对齐：工作电压（MICBIAS）、灵敏度、方向性（全向/指向）、尺寸与焊盘（若为贴片）。

---

## 四、引脚与电气汇总（来自代码）

| 功能 | GPIO/接口 | 说明 |
|------|-----------|------|
| I2S MCLK | 2 | 主时钟 |
| I2S BCLK | 17 | 位时钟 |
| I2S WS (LRCK) | 45 | 帧同步 |
| I2S DOUT | 15 | 送 ES8311（播放） |
| I2S DIN | 16 | 来自 ES7210（录音） |
| 功放使能 PA | 46 | 高有效使能外部 PA |
| Codec I2C | SDA=8, SCL=18 | ES8311、ES7210 共用 I2C 总线 |
| ES8311 I2C 地址 | 默认 (ES8311_CODEC_DEFAULT_ADDR) | 一般为 0x18 |
| ES7210 I2C 地址 | 默认 (ES7210_CODEC_DEFAULT_ADDR) | 一般为 0x40 |

---

## 五、购买建议速查

| 项目 | 建议 |
|------|------|
| **喇叭阻抗** | 以官方原理图为准；无资料时可按 **4Ω** 试配，若原装为 8Ω 则选 8Ω。 |
| **喇叭功率** | 以官方规格为准；无资料时 **1W–2W** 为常见安全范围，不建议明显大于原装。 |
| **功放 (PA)** | 型号未在代码中体现，需查**乐鑫 ESP32-S3-BOX-3 原理图**确认；替换喇叭时需与 PA 输出能力匹配。 |
| **麦克风类型** | **模拟麦克风**（MEMS 或驻极体），接 ES7210 模拟输入与 MICBIAS，**非** I2S 数字麦。 |
| **麦克风规格** | 与板子 MICBIAS 电压、原装麦灵敏度/方向性一致；具体以原理图或原装料号为准。 |

---

## 六、相关文件列表

- `main/boards/esp-box-3/config.h` — 音频与 PA 引脚、采样率、Codec 地址
- `main/boards/esp-box-3/esp_box3_board.cc` — 板级初始化、BoxAudioCodec 构造参数
- `main/audio/codecs/box_audio_codec.cc` / `.h` — ES8311 + ES7210 + PA 使能逻辑
- `main/idf_component.yml` — `espressif/esp_codec_dev` 依赖（ES8311/ES7210 驱动）

如需精确的喇叭阻抗/功率和麦克风型号，建议同时查阅**乐鑫 ESP32-S3-BOX-3 官方硬件规格/原理图**。
