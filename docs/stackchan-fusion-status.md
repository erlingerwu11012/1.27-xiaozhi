# StackChan 融合实施状态与测试说明

本文档记录融合方案的**实施进度**、**当前无板/无舵机下的测试限制**，以及**后续有硬件时的测试指引**。便于以后拿到 StackChan 主板或舵机时按步骤验证。

**方案剩余步骤已全部在代码中完成**（共 8 步：1–5 已实现，6–7 为接口 + 板级桩，8 NFC 本期不做）。当前无板/无舵机时无法做实机测试，仅能编译与烧录；拿到硬件后按本文档第三节、第四节补测即可。

---

## 后续待办清单（供下次继续时使用）

**下次打开项目时**：先看本清单和下面「从哪里开始做」，再按需做代码或测试。

### 代码上还没做的（需要时再补）

| 待办项 | 说明 | 入口位置 | 参考 |
|--------|------|----------|------|
| **IMU 真实驱动** | 移植 BMI270 + motion_detector，检测 Shake/PickUp 后调用 OnImuEvent 和 modifier | `main/boards/stackchan/stackchan_board.cc` 里 **InitializeImu()**（当前为空，注释已写清调用方式） | Stackchan 固件 `hal/hal_imu.cpp`、`hal/drivers/bmi270/`、`hal/utils/motion_detector/` |
| **HeadPet 真实驱动** | 移植 Si12T + hal_head_touch，识别 Press/Release/Swipe 后调用 OnHeadPetGesture 和 modifier | `main/boards/stackchan/stackchan_board.cc` 里 **InitializeHeadPet()**（当前为空，注释已写清调用方式） | Stackchan 固件 `hal/hal_head_touch.cpp`、`hal/drivers/Si12T/` |
| **摄像头对齐（可选）** | 若原厂 Stackchan 用不同 sensor 或 pipeline，可对照原厂 stackchan_camera 再对齐 | `main/boards/stackchan/stackchan_board.cc` 里 **InitializeCamera()**、`config.h` 摄像头引脚 | Stackchan 固件 `hal/board/stackchan_camera.cc` |

### 测试上还没做的（有硬件后再做）

- 舵机实机转动（需机身 + CONFIG_STACKCHAN_USE_SCSERVO=y）
- 摄像头实机预览/拍照（需 StackChan 板）
- 显示与表情实机验证（需 StackChan 板 + 屏）
- IMU 晃动/拿起实机验证（需板 + 上述 IMU 驱动接入后）
- HeadPet 摸头/松手实机验证（需机身 + 上述 HeadPet 驱动接入后）

### 下次继续时从哪里开始做

1. **若先拿到 StackChan 主板（无机身/舵机）**  
   → 选 StackChan 板型编译烧录，先做**第三节 3.2 摄像头、3.5 显示与表情**的补测；舵机保持 StubServo 即可。

2. **若拿到机身 + 舵机**  
   → 打开 CONFIG_STACKCHAN_USE_SCSERVO，按**第三节 3.1 舵机**补测；再按**第四节**做摄像头/显示等。

3. **若要接 IMU（晃动/拿起）**  
   → 从 **InitializeImu()** 入手：移植 BMI270 + motion_detector，在检测到事件时按函数内注释调用 `Application::GetInstance().OnImuEvent(...)` 和 `GetStackChan().getModifier(imu_modifier_id_)` 转成 `IMUMotionModifier*` 后 `SetEvent(...)`。  
   → 相关接口：`main/application.h`（OnImuEvent）、`main/stackchan/modifiers/imu.h`（ImuMotionEvent、SetEvent）。

4. **若要接 HeadPet（摸头）**  
   → 从 **InitializeHeadPet()** 入手：移植 Si12T + hal_head_touch，在识别到手势时按函数内注释调用 `Application::GetInstance().OnHeadPetGesture(gesture)` 和 `getModifier(head_pet_modifier_id_)` 转成 `HeadPetModifier*` 后 `TriggerHappy()` / `TriggerRelease()`。  
   → 相关接口：`main/application.h`（OnHeadPetGesture）、`main/stackchan/modifiers/head_pet.h`（TriggerHappy / TriggerRelease）。

5. **仅查阅/排查**  
   → 引脚与接线看 **`main/boards/stackchan/config.h`**、**`main/boards/stackchan/README.md`**；方案全文看 **`docs/stackchan-fusion-plan.md`**。

---

## 一、当前情况说明（无板 / 无舵机）

- **现状**：手头**没有** M5Stack StackChan 主板，**没有**机身舵机（yaw/pitch）。
- **影响**：以下能力**无法在真机上验证**，仅能保证代码已接好、编译通过；拿到硬件后再做实机测试。
- **可做**：在其它 ESP32-S3 板型上**不选** StackChan 板型时，行为与融合前一致；选 StackChan 板型时可在无舵机/无头触摸/无 IMU 情况下编译并烧录，表情与逻辑可先跑通（舵机为 StubServo 不动作）。

---

## 二、方案步骤与完成状态

| 步骤 | 内容 | 状态 | 无硬件时能否验证 |
|------|------|------|------------------|
| 1 | Kconfig + 板型骨架（CONFIG_BOARD_TYPE_STACKCHAN、boards/stackchan/） | ✅ 已完成 | 可选 StackChan 板型编译/烧录到其它 S3 板，仅部分外设不工作 |
| 2 | stackchan 核心移植（avatar/motion/modifiers/utils，uitk 替代） | ✅ 已完成 | 可编译；表情/动画逻辑依赖显示与 update 循环，需有屏或仿真 |
| 3 | StackChanAvatarDisplay（SetEmotion/SetChatMessage、LVGL 定时器） | ✅ 已完成 | 需有 StackChan 板型 + 显示屏；无板则无法看表情 |
| 4 | 舵机 + Motion（ScServo UART/Feetech、StubServo、Kconfig 选项） | ✅ 已完成 | **无舵机无法测试**：需机身 + 使能 CONFIG_STACKCHAN_USE_SCSERVO 才动作 |
| 5 | 摄像头（Board::GetCamera） | ✅ 已对接 | 当前使用 Esp32Camera + config.h 引脚；**无板无法测试**实拍与预览 |
| 6 | IMU（BMI270 + 事件回调） | 🔶 接口已就绪，驱动为桩 | **无板无法测试**：需板载 IMU，并接入真实驱动后 OnImuEvent / IMUMotionModifier |
| 7 | HeadPet（Si12T 三区触摸 + 手势回调） | 🔶 接口已就绪，驱动为桩 | **无板无法测试**：需机身头触摸，并接入真实驱动后 OnHeadPetGesture / HeadPetModifier |
| 8 | NFC | ⏸ 本期不做 | 标为后续扩展，无实现 |

---

## 三、无法在无硬件下测试的项（后续补测清单）

拿到 **StackChan 主板 + 机身** 后，建议按下面顺序做一次完整验证：

### 3.1 舵机（yaw/pitch）

- **条件**：StackChan 机身接好，串口接线正确（见 `main/boards/stackchan/config.h`：SERVO_TX_PIN / SERVO_RX_PIN / SERVO_BAUD）。
- **配置**：menuconfig 中打开 **Use real SCServo for yaw/pitch motion (StackChan board)**（CONFIG_STACKCHAN_USE_SCSERVO=y）。
- **验证**：烧录后应看到机身水平/俯仰转动；idle、speaking 等 modifier 会驱动舵机。
- **未测**：当前无舵机，**未做**实机转动测试。

### 3.2 摄像头

- **条件**：StackChan 主板（CoreS3 带摄像头），引脚已在 config.h 中配置。
- **验证**：启动后预览/拍照是否正常（Application 与协议侧已有调用 GetCamera()）。
- **未测**：当前无板，**未做**实机摄像与预览测试。

### 3.3 IMU（晃动/拿起等）

- **条件**：板载 BMI270（或后续接入的 IMU）；驱动中在检测到 Shake/PickUp 等时调用 `Application::GetInstance().OnImuEvent(...)`，并转发给 `GetStackChan().getModifier(imu_modifier_id_)->SetEvent(...)`。
- **验证**：晃动/拿起设备时，表情或动作是否有对应反应（若已实现 IMU modifier 逻辑）。
- **未测**：当前无板，且驱动为桩，**未做**实机 IMU 测试。

### 3.4 HeadPet（头触摸三区）

- **条件**：机身 Si12T 三区触摸接好；驱动中在识别 Press/Release/Swipe 等手势后调用 `Application::GetInstance().OnHeadPetGesture(...)`，并转发给 `GetStackChan().getModifier(head_pet_modifier_id_)->TriggerHappy()` / `TriggerRelease()`。
- **验证**：摸头/松手时，表情或动作是否有对应反应。
- **未测**：当前无板，且驱动为桩，**未做**实机 HeadPet 测试。

### 3.5 显示与表情

- **条件**：StackChan 板型 + 显示屏（CoreS3 自带屏）。
- **验证**：SetEmotion / SetChatMessage 与 Blink、IdleMotion、Speaking 等 modifier 是否正常显示与更新。
- **未测**：当前无板，**未做**实机显示与表情测试。

---

## 四、后续测试指引（有硬件时）

1. **拿到 StackChan 主板后**
   - 在 menuconfig 选择板型 **M5Stack StackChan**，按需打开 **Use real SCServo for yaw/pitch motion**。
   - 编译、烧录，先确认启动与显示是否正常（若仍无机身，舵机保持 StubServo 即可）。
2. **接上机身与舵机后**
   - 打开 CONFIG_STACKCHAN_USE_SCSERVO，确认 UART 引脚与波特率与机身一致，再测 yaw/pitch 转动与 idle/speaking 动作。
3. **IMU / HeadPet**
   - 当前为接口 + 桩；实机测试前需接入真实 BMI270 / Si12T 驱动，并在检测到事件时调用 `OnImuEvent` / `OnHeadPetGesture` 及对应 modifier 的 `SetEvent` / `TriggerHappy` / `TriggerRelease`（参见 `main/boards/stackchan/stackchan_board.cc` 中注释）。
4. **引脚与接线**
   - 以 **`main/boards/stackchan/config.h`** 与 **`main/boards/stackchan/README.md`** 为准；焊接与接线按该目录说明操作。

---

## 五、代码与配置要点（便于以后排查）

- **舵机**：ScServo 实现见 `main/stackchan/motion/sc_servo.cc`（Feetech 协议）；板级创建见 `main/boards/stackchan/stackchan_board.cc` 中 `InitializeStackChan()`，CONFIG_STACKCHAN_USE_SCSERVO 为 y 时使用 ScServo，否则 StubServo。
- **IMU / HeadPet**：Application 接口在 `main/application.h`（OnImuEvent / OnHeadPetGesture）；modifier 注入 API 见 `main/stackchan/modifiers/imu.h`（SetEvent）、`main/stackchan/modifiers/head_pet.h`（TriggerHappy / TriggerRelease）；Board 中已注册 IMU/HeadPet modifier 并保存 id，注释中写明“接入驱动后”如何转发事件。
- **摄像头**：已使用 Esp32Camera，引脚与初始化在 `main/boards/stackchan/stackchan_board.cc` 的 `InitializeCamera()` 与 `config.h`。

---

## 六、文档与方案依据

- 融合方案正文：**`docs/stackchan-fusion-plan.md`**
- 板型引脚与说明：**`main/boards/stackchan/config.h`**、**`main/boards/stackchan/README.md`**
- 本文档在**无板/无舵机**情况下编写，待有硬件后按第三节与第四节补测并更新“未测”项为“已测”即可。

---

**下次继续时**：可让助手先阅读本文档（尤其是**「后续待办清单」**与**「下次继续时从哪里开始做」**），即可知道剩余哪些没做、从哪里开始做。

---

## 组装/焊接相关文件一览

**下一步是组装、焊接时**，以下文件涉及引脚定义与接线，请以这些为准：

| 文件路径 | 用途 | 给组装/焊接人员看的要点 |
|----------|------|--------------------------|
| **`main/boards/stackchan/config.h`** | 本板型**全部引脚与硬件参数**的宏定义（音频 I2S、Codec I2C、显示屏、摄像头 D0~D7/VSYNC/HREF/PCLK、按键、舵机 UART 等）。 | 每个 `#define` 旁有简短中文注释；未使用引脚为 `GPIO_NUM_NC`；对应 M5Stack StackChan / CoreS3 + 机身。 |
| **`main/boards/stackchan/README.md`** | **引脚一览表**（GPIO 号、功能、备注）、产品页链接、焊接与接线说明。 | 焊接与接线请以本表及 `config.h` 为准；可直接按表核对 GPIO 与功能，无需翻代码。 |
| **`main/boards/stackchan/stackchan_board.cc`** | 板级初始化与驱动（显示、摄像头、音频、舵机、触摸等）。 | 若需查某外设在代码里具体用哪几个引脚，可在此文件中搜索 `DISPLAY_`、`CAMERA_PIN_`、`SERVO_`、`AUDIO_` 等宏名，与 `config.h` 对照。 |
| **`docs/stackchan-fusion-plan.md`** | 融合方案正文。 | 第九节「官方 PCB 说明与融合后引脚/文档位置」、第十节 FAQ 中 Q2「引脚定义与焊接」说明本板型引脚与文档位置。 |

**汇总**：组装与焊接时，**主要看** `main/boards/stackchan/config.h` 和 **`main/boards/stackchan/README.md`**；需要查某外设对应引脚时再配合 `stackchan_board.cc` 里的宏名搜索。
