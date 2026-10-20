# 1.27-xiaozhi 融合 Stackchan 能力 — 修改方案（待审核）

## 一、目标与范围

### 1.1 融合目标

- **保留**：1.27-xiaozhi 为主代码库（Application、Board、协议、MCP、您的云端与 APP 对接方式均不变）。
- **新增**：在 1.27-xiaozhi 中可选地具备 Stackchan 的以下能力：
  - **表情与动作**：Stackchan 的 Avatar（表情、眼睛、嘴巴、气泡）+ Motion（舵机云台）+ 动画与 Modifier（眨眼、呼吸、闲逛、摸头、说话时动作等）。
  - **硬件**：摄像头、IMU、触摸（HeadPet 三区触摸）、NFC（若 Stackchan 固件中有实现则一并移植）。
- **不引入**：Stackchan 的云服务、iOS/Web APP、WebSocket Avatar、BLE 配网/AppConfig、Reminder 等与“Stackchan 云/APP”强相关的逻辑；您继续使用自己的云端与 APP。

### 1.2 适用板型

- 通过**新板型**（如 `stackchan` 或 `m5stack-stackchan`）启用上述能力，与现有 70+ 板型并列。
- 其他板型不编译 Stackchan 相关代码，行为与现在完全一致。

---

## 二、架构与依赖关系

### 2.1 当前差异简要

| 维度 | 1.27-xiaozhi | Stackchan 固件 |
|------|--------------|-----------------|
| 主循环 | `Application::GetInstance().Start()` | Mooncake 应用框架 + `GetMooncake().update()` |
| 显示 | Board → Display（LvglDisplay / LcdDisplay 等） | HAL → StackChanAvatarDisplay（继承 xiaozhi 的 LvglDisplay） |
| 小智 | 内置 Application + 协议 | 通过 hal_bridge 调用 xiaozhi-esp32 子模块的 Board/Application |
| 表情/动作 | 无 | stackchan 命名空间（avatar + motion + modifiers） |
| 硬件抽象 | Board + 各板目录 | HAL（hal_servo, hal_imu, hal_head_touch 等） |

### 2.2 融合后架构（目标）

```
1.27-xiaozhi (主)
├── main.cc → Application::Start()  [不变]
├── application.cc / board / display / protocols / mcp  [不变]
├── main/stackchan/           [新增，从 Stackchan 移植]
│   ├── avatar/              表情（眼睛、嘴、气泡、decorators）
│   ├── motion/              舵机云台（yaw/pitch）
│   ├── animation/           动画
│   ├── modifiers/           眨眼、呼吸、闲逛、摸头、说话等
│   ├── json/                JSON 配置
│   └── stackchan.cpp/h      StackChan 主类
├── main/display/
│   └── stackchan_avatar_display.cc/h   [新增] 继承 LvglDisplay，内嵌 StackChan avatar
├── main/boards/stackchan/    [新增板型]
│   ├── stackchan_board.cc/h            Board 实现（Display/Camera/舵机/IMU/触摸/NFC）
│   ├── stackchan_camera.cc/h           摄像头（从 Stackchan hal/board 移植）
│   └── stackchan_*.cc                   其他板级驱动
├── main/hal_stackchan/       [可选目录] 或把驱动放在 boards/stackchan/
│   ├── hal_servo.cc         舵机（SCServo）
│   ├── hal_imu.cc            IMU（BMI270）
│   ├── hal_head_touch.cc     头部三区触摸（Si12T）
│   └── nfc/                  若存在则移植 NFC 驱动
└── Kconfig / CMakeLists      仅当 CONFIG_BOARD_TYPE_STACKCHAN 时编译上述模块
```

- **显示**：新板型使用 `StackChanAvatarDisplay`，在 `SetEmotion`/`SetChatMessage`/设备状态变化时驱动 StackChan 的 avatar 与 modifiers（如 speaking、idle、blink），与现有 Application 逻辑对接。
- **动作**：同一板型提供舵机（yaw/pitch），由 StackChan 的 motion 与 modifiers 驱动；无舵机板型不编译 motion/舵机相关代码。
- **摄像头/IMU/触摸/NFC**：作为该板型的可选硬件，由 Board 或板级 HAL 初始化，通过现有或少量新接口暴露给 Application（如 IMU/触摸事件回调）。

---

## 三、分项修改方案

### 3.1 表情与动作（StackChan Avatar + Motion）

**3.1.1 移植目录**

- 从 `Stackchan/firmware/main/stackchan/` 拷贝到 `1.27-xiaozhi/main/stackchan/`：
  - `avatar/`（含 skins/default、decorators、elements）
  - `motion/`（motion.cpp/h、servo.cpp/h）
  - `animation/`
  - `modifiers/`（blink、breath、dance、head_pet、idle_motion、imu、speaking、timed 等）
  - `json/`（json_helper）
  - `utils/`（object_pool、random、timer）
  - `stackchan.cpp/h`、`modifiable.h`

**3.1.2 依赖处理（重要）**

Stackchan 的 `stackchan` 模块大量使用 **smooth_ui_toolkit**（`uitk::Vector2i`、`uitk::clamp`、`uitk::map_range`、`uitk::AnimateValue`、`uitk::SpringOptions_t`、`uitk::lvgl_cpp::Container/Image/Label` 等）。

- **方案 A（推荐，依赖最少）**：不引入 smooth_ui_toolkit，在 1.27-xiaozhi 内做最小替换：
  - 用 `struct Vector2i { int x; int y; };` 或 `std::pair<int,int>` 替代 `uitk::Vector2i`。
  - 用 `std::max/min` 或内联 `clamp`/`map_range` 实现替代 `uitk::clamp`、`uitk::map_range`。
  - 动画：用简单线性插值或 esp_timer 周期更新替代 `uitk::AnimateValue`/`SpringOptions`（或引入一个仅含这些工具的小头文件）。
  - Avatar 的 LVGL 部分：用 1.27-xiaozhi 已有的 **lvgl** 与 `lvgl_display` 直接写 `lv_obj_t*` 创建/更新，替代 `uitk::lvgl_cpp::Container/Image/Label`。
- **方案 B**：将 smooth_ui_toolkit 作为组件加入 1.27-xiaozhi（idf_component 或子模块），移植时几乎不改 stackchan 源码，但会多一个较大依赖。

**3.1.3 显示层对接**

- 新增 `StackChanAvatarDisplay`（参考 `Stackchan/firmware/main/hal/board/stackchan_display.cc/.h`）：
  - 继承 1.27-xiaozhi 的 `LvglDisplay`（`main/display/lvgl_display/`）。
  - 在构造/初始化时创建 `stackchan::StackChan` 实例，挂上 default avatar 与 motion（若本板有舵机）。
  - 重写 `SetEmotion`、`SetChatMessage`、`SetStatus` 等，内部调用 StackChan 的 `updateAvatarFromJson`/`updateMotionFromJson` 或直接驱动对应 modifier（如 speaking、idle）。
  - 使用 LVGL 定时器或 Application 的时钟在每帧调用 `GetStackChan().update()`，实现表情与动作的更新。
- 主题（LvglTheme/LvglThemeManager）：1.27-xiaozhi 已有 `lvgl_theme`，与 Stackchan 的 `LvglTheme` 对齐接口或做一层薄适配，使 StackChanAvatarDisplay 能复用现有主题与资源。

**3.1.4 动作（舵机）对接**

- 仅当 `CONFIG_BOARD_TYPE_STACKCHAN` 且硬件有舵机时编译：
  - 移植 `Stackchan/firmware/main/hal/hal_servo.cpp` 及 `hal/drivers/SCServo_lib`。
  - 板级初始化时创建 `stackchan::motion::Motion`（yaw/pitch 两个 Servo），并挂到 `StackChan` 上。
  - StackChan 的 modifiers（idle_motion、speaking、head_pet 等）通过现有 Motion 接口驱动舵机，无需改 Application 主流程。

---

### 3.2 摄像头

- 1.27-xiaozhi 已有 `Camera` 接口与 `esp32_camera` 等实现；部分板型已有摄像头。
- **Stackchan 板型**：移植 `Stackchan/firmware/main/hal/board/stackchan_camera.cc/.h`，实现 1.27-xiaozhi 的 `Camera` 接口（或作为该板 `Board::GetCamera()` 的返回实现）。
- 若 Stackchan 使用与现有 esp32_camera 相同的驱动，则主要做引脚与初始化参数对齐；若有专用 pipeline，则一并移植到该板目录下，不污染通用 camera 代码。

---

### 3.3 IMU

- 移植 `Stackchan/firmware/main/hal/hal_imu.cpp` 及 `hal/drivers/bmi270/`、`hal/utils/motion_detector/` 到 1.27-xiaozhi。
- 放置位置：`main/boards/stackchan/` 或 `main/hal_stackchan/`，仅在该板型下编译。
- **对接方式**：
  - 在 Board 或板级初始化中启动 IMU 任务；检测到 Shake/PickUp 时，通过 **回调或事件** 上报给 Application（例如 `Application::OnImuEvent(Shake)`），不依赖 Stackchan 的 HAL 全局单例。
  - 若启用 StackChan 表情/动作，可在 StackChan 侧注册 IMU modifier，将同一事件转发给 StackChan（如点头、摇头反应）。

---

### 3.4 触摸（HeadPet，三区头触摸）

- Stackchan 的“头触摸”由 **Si12T** 三区电容读取，实现于 `hal_head_touch.cpp`（与屏触摸分离）。
- 移植 `hal_head_touch.cpp` 及 `hal/drivers/Si12T/` 到 1.27-xiaozhi，仅 Stackchan 板型编译。
- **对接方式**：
  - 识别手势：Press、Release、SwipeForward、SwipeBackward。
  - 通过 Board 或 Application 的**回调/事件**上报（例如 `Application::OnHeadPetGesture(gesture)`），由您现有逻辑或 APP 协议处理。
  - 若启用 StackChan，可将同一手势连到 StackChan 的 head_pet modifier，驱动“摸头”动画与舵机动作。

---

### 3.5 NFC

- Stackchan 产品说明带 NFC，若其固件中有独立 NFC 驱动（非 Si12T 复用），则在该板型下单独移植并暴露为 Board 能力或独立接口；若目前仅 Si12T 用于触摸，则本项可标为“后续扩展”，先不做。

---

### 3.6 不移植内容（明确排除）

- **Mooncake** 应用框架、App Launcher、AppSetup、AppAvatar（视频通话）、AppEspnowControl 等。
- **BLE** 配网/AppConfig、WebSocket Avatar、Reminder 等与 Stackchan 云/APP 相关的逻辑。
- Stackchan 的 `main.cpp`、`repos.json` 拉取的 mooncake/smooth_ui_toolkit 等，仅在采用方案 B 时考虑引入 smooth_ui_toolkit 一个库。

---

## 四、构建与配置

### 4.1 Kconfig

- 在 `Kconfig.projbuild` 中新增：
  - `CONFIG_BOARD_TYPE_STACKCHAN`（或 `CONFIG_BOARD_TYPE_M5STACK_STACKCHAN`），与现有 `CONFIG_BOARD_TYPE_*` 同级。
- 仅当该选项为 y 时：
  - 编译 `main/stackchan/`、`StackChanAvatarDisplay`、`boards/stackchan/` 及 hal_stackchan（舵机/IMU/头触摸/NFC 等）。

### 4.2 CMakeLists.txt

- 在 `main/CMakeLists.txt` 的板型分支中增加 `CONFIG_BOARD_TYPE_STACKCHAN` 对应分支，设置 `BOARD_TYPE=stackchan` 及所需字体/资源。
- 新增源列表：
  - `stackchan/` 下所有需要的源文件；
  - `display/stackchan_avatar_display.cc`；
  - `boards/stackchan/*.cc` 及 hal_stackchan 下的驱动。
- 若采用方案 A，无需添加 smooth_ui_toolkit 的 `PRIV_REQUIRES`；若采用方案 B，则增加对应 component。

### 4.3 依赖组件

- 舵机：SCServo 库（已包含在 Stackchan 的 `hal/drivers/SCServo_lib`，随移植拷贝）。
- IMU：BMI270（Stackchan 的 `bmi270` 目录），仅 Stackchan 板型。
- 触摸：Si12T（Stackchan 的 `Si12T` 目录），仅 Stackchan 板型。
- 其他（LVGL、esp_lcd、nvs 等）沿用 1.27-xiaozhi 现有组件。

---

## 五、集成点与调用关系

### 5.1 Application 与 StackChan 的衔接

- **显示**：  
  `Application` 照常调用 `Board::GetDisplay()->SetEmotion(...)` / `SetChatMessage(...)` / `SetStatus(...)`。  
  对 Stackchan 板型，`GetDisplay()` 返回 `StackChanAvatarDisplay`，其内部再驱动 StackChan 的 avatar 与 modifiers，无需改 Application 其它逻辑。

- **事件**（可选）：  
  - IMU：板级或 hal_stackchan 在检测到 Shake/PickUp 后调用 `Application::OnImuEvent(...)`（需在 Application 中新增该接口并实现空默认行为）。  
  - HeadPet：板级在识别手势后调用 `Application::OnHeadPetGesture(...)`（同样新增接口+空默认）。  
  - 若启用 StackChan，在 Board 或 Display 初始化时，将这些事件再转发给 StackChan 的 modifier（如 imu、head_pet）。

### 5.2 与您云端/APP 的关系

- 协议、MCP、WebSocket/MQTT 等保持现有实现；不引入 Stackchan 的云端 API 与 APP 协议。
- 若您希望把“摸头”“晃动”等事件上报到自己的云端或 APP，只需在 `OnHeadPetGesture`/`OnImuEvent` 的实现里调用您已有的发送逻辑即可。

---

## 六、实施顺序建议

1. **Kconfig + 板型骨架**：新增 `CONFIG_BOARD_TYPE_STACKCHAN` 与 `boards/stackchan/` 最小 Board（仅显示+音频+网络，先不接 StackChan）。
2. **stackchan 核心移植**：按 3.1 移植 `stackchan/` 并处理 smooth_ui_toolkit 依赖（方案 A 或 B），保证能编译通过。
3. **StackChanAvatarDisplay**：实现继承 LvglDisplay 的 StackChan 显示层，在栈上或板级创建 StackChan 并驱动 avatar，与 SetEmotion/SetChatMessage 对接。
4. **舵机 + Motion**：移植 SCServo 与 hal_servo，在板级挂载 Motion 到 StackChan，测试 idle/speaking 等 modifier。
5. **摄像头**：移植 stackchan_camera，实现 Board::GetCamera()。
6. **IMU**：移植 BMI270 + motion_detector，实现事件回调并与 Application/StackChan 对接。
7. **HeadPet**：移植 Si12T + hal_head_touch，实现手势回调。
8. **NFC**：视固件中是否已有实现再决定是否在本期移植。

---

## 七、风险与注意点

- **smooth_ui_toolkit 替换量**：若选方案 A，需系统替换 `uitk::*` 与 `uitk::lvgl_cpp::*`，并重写少量动画逻辑，工作量中等但可完全掌控依赖。
- **LvglDisplay 与 LvglTheme**：Stackchan 的 `StackChanAvatarDisplay` 依赖 xiaozhi 的 LvglDisplay/LvglTheme；需确认 1.27-xiaozhi 的 `display/lvgl_display` 与 `lvgl_theme` 与 Stackchan 使用的接口一致（类名、SetTheme、字体等），必要时做薄适配层。
- **线程与锁**：StackChan 的 `update()` 需在 LVGL 线程或带锁环境下调用，与 1.27-xiaozhi 的显示刷新统一，避免竞态。
- **Flash/PSRAM**：Stackchan 表情与资源可能增加占用，建议在 sdkconfig 与分区表中为 stackchan 板型预留余量。

---

## 八、审核确认项 — 最终确认（实施时按此执行）

以下为**已全部确认**的项，实施时严格按此执行；您审核方案通过后再动手改代码。

| 项 | 决定 |
|----|------|
| **板型命名** | 使用 **`stackchan`**。 |
| **表情/舵机动画依赖库** | **方案 A**：不引入 smooth_ui_toolkit，在 1.27-xiaozhi 内自己写最小替代（如 stackchan_utils），便于后续加更多表情与动画。 |
| **显示接口对接** | 实施时写好一层**薄适配**（桥接 LvglDisplay/LvglTheme 与 StackChan 显示）；若使用中不合适再调节。 |
| **刷新方式** | 按方案执行：StackChan 的 `update()` 通过 LVGL 定时器或与 `lv_timer_handler()` 同上下文调用，与显示刷新接好。 |
| **Flash/内存** | 使用**官方 StackChan 主板**，按官方配置即可，方案中不单独考虑。 |
| **官方 PCB 与引脚/焊接文档** | 方案中明确官方 PCB 定义，融合后引脚定义与焊接说明的**位置**见「九、官方 PCB 说明与融合后引脚/文档位置」。 |
| **事件接口** | **要加**：在 Application 中新增 `OnImuEvent` / `OnHeadPetGesture`（默认空实现），供 stackchan 板型调用；您后续只打算使用 stackchan 主板，其它板型暂不用。 |
| **NFC** | **本期不做**，标为后续扩展。 |
| **其它板型** | **仅**新板型 `stackchan` 使用 StackChan 表情与动作，不在其它板型上启用；不需要多板型共用选项。 |

本方案仅作设计与评审用，**不会在未得到您明确同意前修改仓库代码**。您审核方案通过后再执行修改。

---

## 九、官方 PCB 说明与融合后引脚/文档位置（供焊接人员查阅）

本节明确：**官方 PCB 是什么**，以及**融合完成后，引脚定义与焊接说明在仓库里的位置**，方便焊接工作人员直接找到并对照。

### 9.1 官方 PCB 板子是什么

本项目采用的**官方开发板**为 **M5Stack StackChan**，由以下两部分组成：

| 部分 | 说明 |
|------|------|
| **主控单元** | **M5Stack CoreS3**：ESP32-S3 双核 240MHz、16MB Flash、8MB PSRAM，Wi-Fi + BLE；集成 2.0 寸电容触摸屏、0.3MP 摄像头、接近传感器、9 轴 IMU、microSD、1W 扬声器、双麦克风、电源/复位键。 |
| **机身** | 与主控通过接口连接：USB-C 供电与数据、700mAh 电池、**两个反馈舵机**（水平 360° / 俯仰 90°）、12 颗 RGB LED、红外收发、**三区触摸**（HeadPet，Si12T）、NFC 模块（本期固件不实现）。 |

- **产品/预购页**：https://m5stack.com/stackchan  
- **CoreS3 文档**：https://docs.m5stack.com/en/core/CoreS3  

即：**官方 PCB = M5Stack StackChan 整机**（CoreS3 主控 + 机身一体），无需您自行画 PCB；融合后固件按该硬件引脚与接口编写，烧录到该官方主板上即可运行。

### 9.2 融合完成后，引脚定义与焊接说明在哪里

融合实施完成后，所有与 **stackchan 板型** 相关的引脚定义与焊接用说明，均放在 1.27-xiaozhi 仓库的以下位置，**便于焊接工作人员查找**：

| 位置（仓库内路径） | 内容 | 给焊接人员看的要点 |
|--------------------|------|----------------------|
| **`main/boards/stackchan/config.h`** | 本板型**全部引脚与硬件参数**的宏定义（音频 I2S、Codec I2C、显示屏、摄像头 D0~D7/VSYNC/HREF/PCLK、按键、舵机 UART、I2C 等）。 | 文件顶部会注明「对应 M5Stack StackChan 官方原理图/版本」；每个 `#define` 旁有简短中文注释（如 `// 摄像头数据 D0`、`// 舵机串口 TX`）；未使用引脚为 `GPIO_NUM_NC`，便于区分「不用接」。 |
| **`main/boards/stackchan/README.md`**（实施时新增） | **焊接/接线一览**：板型名称、官方 PCB 说明、引脚表（GPIO 号、功能、备注）、注意事项。 | 焊接人员可直接打开该 README，按表核对 GPIO 与功能，无需翻代码。 |
| **`main/boards/stackchan/` 目录下其它 `.cc/.h`** | 板级初始化与驱动（显示、摄像头、音频、舵机、IMU、触摸等）。 | 若需查某外设具体用哪几个引脚，可配合 `config.h` 中的宏名在该目录内搜索。 |

实施时会保证：

1. **`config.h`** 中所有与焊接/接线相关的宏，均有**中文注释**，且**顶部注明**所对应的官方 PCB/原理图（如「M5Stack StackChan / CoreS3 + 机身」及可查到的文档版本或链接）。  
2. **`main/boards/stackchan/README.md`** 中提供**引脚一览表**（GPIO 编号、功能名称、备注），并写明「焊接与接线请以本表及 `config.h` 为准」，方便焊接人员单独打开此文档即可作业。  

您审核通过后，实施阶段会按上述约定在 **`main/boards/stackchan/`** 下写好 `config.h` 与 `README.md`；完成后只需告知焊接人员：**看 1.27-xiaozhi 仓库里的 `main/boards/stackchan/` 目录，引脚看 `config.h`，一览表看 `README.md`**。

---

## 十、补充 FAQ（PCB / 引脚 / 蓝牙配网）

### Q1：PCB 开发板是否需要重新画？

**一般不需要。**

- **情况 A：您用的是自己的 ESP32-S3 主板**  
  融合只是在代码里增加一个**新板型**（如 `stackchan`）。您现有的 PCB 不用改，只需在 1.27-xiaozhi 里为您的板子**增加或沿用现有板型配置**，把您板子上的引脚在 `config.h` 里定义好即可。融合后的代码不会要求您重画 PCB。

- **情况 B：您打算做一块“和 StackChan 硬件一样”的板子**  
  若按 M5Stack StackChan 的引脚来画板，可以参照融合后 `boards/stackchan/` 里的 `config.h`（会从 Stackchan 固件移植过来）按图焊接，这时是**新做一块板**，而不是“重画现有板”。

- **情况 C：现有板型想加 StackChan 表情/动作**  
  若选的是“在现有板型（如 m5stack-core-s3）上启用 StackChan 能力”，只需在 Kconfig 里让该板型也编译 stackchan 相关代码，并保证该板型已有摄像头/舵机等所需外设的引脚定义，**不需要为此重画 PCB**。

结论：**按现有主板做融合时，不需要重新画 PCB；只有要做一块全新 StackChan 兼容板时，才需要按新引脚图设计/画板。**

---

### Q2：融合后的代码里是否有引脚定义，方便焊接？

**有。** 1.27-xiaozhi 和 Stackchan 都采用**每板一个 `config.h`（或等价头文件）集中写引脚**的方式，融合后会保持这种做法，方便对照焊接。

- **现有风格（1.27-xiaozhi）**  
  每个板型目录下通常有 `config.h`，例如：
  - 音频：`AUDIO_I2S_GPIO_MCLK/WS/BCLK/DIN/DOUT`、`AUDIO_CODEC_I2C_SDA_PIN/SCL_PIN`
  - 显示：`DISPLAY_SDA_PIN/SCL_PIN`、`DISPLAY_BACKLIGHT_PIN`、`DISPLAY_WIDTH/HEIGHT`
  - 摄像头：`CAMERA_PIN_D0~D7`、`CAMERA_PIN_VSYNC/HREF/PCLK` 等
  - 按键：`BOOT_BUTTON_GPIO`、`VOLUME_UP_BUTTON_GPIO` 等  
  未使用的引脚会写成 `GPIO_NUM_NC`，便于区分“不用接”。

- **融合后**  
  - 新增的 **stackchan 板型**会在 `main/boards/stackchan/config.h` 里集中定义：LCD、摄像头、I2C（音频/IMU/触摸）、舵机 UART、HeadPet（Si12T）等本方案用到的 GPIO，并加上简短注释（如 `// 摄像头 D0`、`// 舵机串口 TX`）；NFC 本期不做，不列入。焊接与引脚一览见**第九节**及该目录下 `README.md`。
  - 若您用的是**自己的 ESP32-S3 板**，只需在您对应的板型目录里维护一份 `config.h`，把您实际焊接的引脚填进去即可；融合不会改您现有板型的引脚文件，只会**增加** stackchan 板型的引脚定义。

建议：在 `config.h` 顶部加一两行注释注明“对应原理图/版本”，焊接时直接对照该文件即可。

---

### Q3：我目前使用 ESP32-S3 主板，代码里已有蓝牙配网，融合会影响吗？

**不会影响。** 融合方案刻意不动您现有的配网和 BLE 用法。

- **当前 1.27-xiaozhi 的配网方式**  
  - 使用 ESP-IDF 的 **BLE + WiFi 配网**：`wifi_provisioning` + `scheme_ble`（见 `boards/common/wifi_board.cc`），即“蓝牙配网”把 WiFi 热点信息写入设备。  
  - `sdkconfig.defaults` 里已开启 `CONFIG_BT_ENABLED`、`CONFIG_BT_NIMBLE_*` 等，与您使用 ESP32-S3 的蓝牙配网一致。

- **融合方案中的约定**  
  - **不引入** Stackchan 的 BLE AppConfig、Stackchan 云/APP 相关逻辑。  
  - **不修改** `wifi_board.cc`、`wifi_provisioning`、现有 BLE 配置。  
  - 新增的 stackchan 相关代码（表情、动作、摄像头、IMU、触摸等）只在**新板型**或您勾选的板型下编译，不会替换或关闭您现有的蓝牙配网。

因此，您继续使用现有 ESP32-S3 主板和现有板型时，**蓝牙配网行为与现在完全一致**；若以后选用“stackchan”板型，也会在保留现有 WiFi/BLE 配网能力的前提下，仅**增加** StackChan 的显示与硬件驱动，不会删掉或覆盖蓝牙配网。

---

## 十一、直接使用 Stackchan 开发板与 3D 外壳

### 能否直接用 Stackchan 的开发板 + 3D 打印外壳？

**可以。** 融合后您**不需要自己画 PCB**，可以直接使用 **M5Stack StackChan 成品开发板**（CoreS3 主控 + 机器人机身：舵机、RGB、触摸、NFC 等），再配上官方或社区的 **3D 打印外壳/结构件**，烧录融合后的 1.27-xiaozhi 固件即可。

### Stackchan 的“板型”在它仓库里吗？

**在。** 在 Stackchan 仓库里，板级相关定义和驱动都在 **`Stackchan/firmware/main/hal/board/`** 下：

| 文件 | 作用 |
|------|------|
| **config.h** | 引脚与硬件参数：音频 I2S、Codec I2C、显示屏、摄像头 D0~D7/VSYNC/HREF/PCLK、按键等（与 M5Stack CoreS3 + StackChan 机身一致） |
| **stackchan.cc** | 板级初始化：电源(AXP2101)、背光、I2C、显示屏、摄像头、触摸等，相当于 1.27-xiaozhi 里一个“板型”的 Board 实现 |
| **stackchan_display.cc/.h** | StackChan 表情显示（继承 LvglDisplay） |
| **stackchan_camera.cc/.h** | StackChan 用摄像头 |
| **cores3_audio_codec.cc/.h** | CoreS3 音频 Codec |
| **hal_bridge.cc/.h** | 与 xiaozhi 的 Board/Display 对接 |

融合时会把上述 **config.h 的引脚与参数** 以及 **stackchan.cc 代表的板级逻辑** 移植到 1.27-xiaozhi 的 **`main/boards/stackchan/`**，作为新的板型。您编译时选 **CONFIG_BOARD_TYPE_STACKCHAN**，烧录到 **M5Stack StackChan 硬件**上，即可“直接用 Stackchan 的开发板”，无需再画 PCB。

### 3D 打印相关

- Stackchan 仓库里 **`app/StackChan/3DModel/stackChanModel.scn`** 是给 **iOS 应用**用的 SceneKit 模型，不是 3D 打印用文件。
- **可打印的外壳/结构件**（STL 等）一般由 M5Stack 或社区提供，可在 M5Stack 官网、StackChan 预购/产品页或开源社区查找；融合方案本身不包含 3D 模型，只保证固件能跑在 StackChan 硬件上。
- 您说的“3D 打印固件”这里理解为：**用 3D 打印的外壳 + StackChan 开发板**；**固件**用融合后的 1.27-xiaozhi 编译出的固件即可。

### 过去的板型要不要删？

按您说的“过去的版型都不打算用了，就留在这儿”——**可以保留不删**。  
融合只是**新增**一个板型 `stackchan`，不会删或改您现有的板型目录；编译时通过 Kconfig 选 `CONFIG_BOARD_TYPE_STACKCHAN` 即可只用 Stackchan 板型，其它板型留在仓库里不影响。

### 直接用 Stackchan 板型，对您的 xiaozhi 代码会造成什么影响？

**几乎没有负面影响，主要是“多一个板型选项”。**

1. **Application 层（您的核心逻辑）**  
   - `application.cc`、协议（WebSocket/MQTT）、MCP、语音、您的云端/APP 对接等**都不需要改**。  
   - 仍然通过 `Board::GetInstance().GetDisplay()`、`GetCamera()` 等接口操作硬件；只是当选择 stackchan 板型时，这些接口背后换成 **StackChan 的显示/摄像头/舵机等实现**。

2. **Board / Display 抽象**  
   - 融合后新增的 **stackchan 板型**会实现 1.27-xiaozhi 里已有的 **Board**、**Display**、**Camera** 等接口（与现有板型一致）。  
   - 对 Application 来说只是“换了一块板子”，不涉及改协议或业务逻辑。

3. **实际影响归纳**  
   - **需要做的**：在 1.27-xiaozhi 里**增加** `boards/stackchan/` 及 stackchan 相关驱动（从 Stackchan 的 `hal/board/` 移植），并在 Kconfig 里增加 **CONFIG_BOARD_TYPE_STACKCHAN**。  
   - **不需要做的**：改您现有的 xiaozhi 业务代码、协议、配网、MCP 等。  
   - **结果**：您用 StackChan 硬件 + 选 stackchan 板型编译烧录后，跑的还是您那套 xiaozhi（语音、MCP、您的云/APP），只是硬件和显示/表情/动作变成 StackChan 的；不会破坏您现有代码，也不会强制您用 Stackchan 的云或 APP。

---

## 十二、风险与审核确认项 — 通俗说明（供您决定是否改）

下面用大白话把**可能的风险**和**需要您拍板的几件事**说清楚，方便您决定“改不改、怎么改”。

---

### 一）风险 — 通俗说

**1. 表情/动画那套代码里，Stackchan 用了一个“工具箱”叫 smooth_ui_toolkit**

- **是什么**：Stackchan 的表情、舵机动画、眼睛嘴巴的位置和弹簧动画等，都依赖这个库里的小工具（比如“二维坐标”“限幅”“插值动画”“LVGL 控件封装”）。
- **风险点**：  
  - 如果**不引入**这个库（方案 A），我们就要在您工程里自己写一套“替代品”（比如用简单结构体代替坐标、用线性插值代替弹簧动画），**工作量中等**，但改完以后您的工程**不依赖**这个库，以后升级、维护都更可控。  
  - 如果**引入**这个库（方案 B），移植会很快、几乎不用改 Stackchan 源码，但您的工程会**多一个第三方依赖**，以后这个库更新或和 ESP-IDF 冲突时，要一起跟着排查。
- **通俗结论**：选 A = 多干点活、少背一个依赖；选 B = 少干活、多背一个依赖。方案里推荐 A，您也可以选 B 换省事。

**2. 显示和主题接口可能对不齐**

- **是什么**：Stackchan 的“表情显示屏”是基于 xiaozhi 的 LvglDisplay 和主题（LvglTheme）做的；但两边仓库可能对“主题叫什么、字体怎么设”等细节不完全一致。
- **风险点**：移植后有可能出现：编译报错、主题名对不上、字体缺失等。一般通过**做一层薄薄的适配**（写几行桥接代码）就能解决，不会动您现有的业务逻辑。
- **通俗结论**：属于**对接时的正常排查**，有风险但可控，改的都是“板型/显示”相关代码，不动您的小智主流程。

**3. 表情/舵机更新要在“正确的时机”调用**

- **是什么**：StackChan 的表情和舵机是每隔一段时间“更新一帧”；这个更新必须和屏幕刷新在**同一个线程**里，或者加锁，否则可能出现花屏、舵机乱动。
- **风险点**：若没把 `StackChan.update()` 放在 LVGL 刷新线程里（或没加锁），理论上会有竞态。方案里会按 1.27-xiaozhi 现有的显示刷新方式接好，避免这个问题。
- **通俗结论**：实现时注意**谁在什么时候调 update** 即可，属于实现细节，不在您业务代码里改。

**4. Flash / 内存可能更吃紧**

- **是什么**：Stackchan 的表情、贴图、动画资源会比现在“只有小智界面”时多一些，占用的 Flash 和 PSRAM 会上去一点。
- **风险点**：如果您的板子或分区表已经比较满，融合后有可能出现“编译通过但烧录失败”或“运行一段时间崩溃”。  
- **通俗结论**：给 **stackchan 板型** 在 sdkconfig 和分区表里**多留一点余量**（Flash/PSRAM），一般就没事；您只用 StackChan 官方板的话，官方硬件本身是够的。

---

### 二）审核确认项 — 通俗说（需要您拍板）

下面几件事需要您**明确选一下**，我们才好按您的选择去改代码。

**1. 板型叫什么名字？**

- **选项**：用 `stackchan`，还是 `m5stack-stackchan`，或者您自己起一个（例如 `my-stackchan`）？  
- **影响**：只是 Kconfig 里选项名和目录名，选哪个都不影响功能，您叫着顺口、和您自己的命名习惯一致即可。

**2. 要不要多一个“工具箱”依赖？（smooth_ui_toolkit）**

- **选项**：  
  - **方案 A**：不引入，我们在您工程里用简单类型和 LVGL 直接写替代 — **无新依赖**，移植时多改一点代码。  
  - **方案 B**：引入 smooth_ui_toolkit 组件 — **多一个依赖**，移植时几乎不改 Stackchan 源码。  
- **影响**：上面“风险 1”已经说过：A = 可控依赖、中等工作量；B = 少工作量、多一个库。您更在意“少依赖”就选 A，更在意“少改代码”就选 B。

**3. 要不要在 Application 里加“事件接口”？**

- **是什么**：比如“设备被晃了一下”（IMU）、“头被摸了一下”（HeadPet），这些事件若要在您的小智或云端里用，就要有一个“入口”把事件报给 Application。  
- **选项**：是否同意在 Application 里**新增**像 `OnImuEvent(...)`、`OnHeadPetGesture(...)` 这样的接口？默认是**空实现**（不做事），只有 stackchan 板型才会去调它；其它板型不受影响。  
- **影响**：同意的话，您之后可以在这些接口里接自己的逻辑（例如上报到您的 APP）；不同意的话，就只做表情/动作，不做“事件上报到 Application”。

**4. NFC 这期做不做？**

- **选项**：  
  - 这期就做：融合时只要 Stackchan 固件里有 NFC 驱动，就一并移植。  
  - 标成“后续扩展”：这期只做表情、动作、摄像头、IMU、触摸，NFC 以后再说。  
- **影响**：若您暂时用不到 NFC，选“后续扩展”可以少改一点、先跑通主功能。

**5. 除了新板型 stackchan，还有没有别的板型也要用 StackChan 表情/动作？**

- **是什么**：例如您是否希望“现有的 m5stack-core-s3 板型”也能用 StackChan 的表情和舵机（同一套代码，两个板型都能选）？  
- **选项**：  
  - 只有新板型 `stackchan` 用 → 不需要改 Kconfig，只编译 stackchan 板型时带表情/动作。  
  - 还有别的板型（如 m5stack-core-s3）也要用 → 需要在 Kconfig 里加选项，让多个板型共用 stackchan 的显示/舵机逻辑。  
- **影响**：若您确定“只用手上的 StackChan 开发板”，选“只有新板型”即可；若以后可能在其他板子上也跑同一套表情，就说一声，我们按“多板型共用”来做。

---

### 三）小结：您怎么决定“是否改”？

- **风险**：主要是“依赖选择”“接口对接”“刷新时机”“Flash/内存”四块，方案里都有对应做法，可控；不涉及推倒重写您的小智逻辑。  
- **确认项**：上面 5 点您只要**按自己需求选一轮**（板型名、A/B 方案、事件接口、NFC 做不做、是否多板型共用），我们就可以按您的选择实施；若某一条您暂时没想好，也可以先选一个“默认”（例如板型名用 `stackchan`、方案 A、NFC 后续扩展），后面再微调。  

您决定“要改”之后，把上述 5 点的选择发给我（或写在文档里），我就按这个来改；若您决定“先不改”，现有方案文档也会一直保留，随时可以再启动。

---

## 十三、已确认项补充说明 + 待定项详细说明（供您决定）

本节为**历史补充说明**：表情库、事件接口、NFC 等已按您的决定写入第八节；此处保留详细说明供实施时参考。**当前仅更新方案文档，不执行代码修改；您审核方案通过后再执行。**

---

### 1. 表情、舵机动画依赖的库 — 能否自己写？以后加更多表情/动画用哪种方式好？

**结论：可以自己写；若您以后要加更多表情和更多舵机动画，推荐用方案 A（不引入 smooth_ui_toolkit，在您工程里写一套最小替代）。**

- **“库”在这里指什么**  
  Stackchan 里用到的 smooth_ui_toolkit，主要是这些**小工具**：  
  - 二维坐标（`Vector2i`）、数值限幅（`clamp`）、区间映射（`map_range`）；  
  - 简单动画（`AnimateValue`、弹簧参数 `SpringOptions`）；  
  - 对 LVGL 的薄封装（`Container`/`Image`/`Label` 等）。  
  没有特别复杂的逻辑，**完全可以由您在 1.27-xiaozhi 里自己实现**：例如用 `struct { int x, y; }` 代替 `Vector2i`，用几行 `min/max` 代替 `clamp`，用线性插值或 `esp_timer` 周期更新代替弹簧动画，用现有 LVGL API 直接建控件代替 `uitk::lvgl_cpp`。

- **“加更多表情、更多舵机动画”靠的是什么**  
  扩展性主要不在这个“工具箱”，而在 **Stackchan 的架构**：  
  - **表情**：avatar 的 skins（默认脸）、decorators（爱心、汗珠、生气等）、elements（眼睛、嘴、气泡）— 您以后可以加新 skin、新 decorator、新元素。  
  - **舵机动画**：modifiers（idle_motion、speaking、head_pet、dance、blink 等）— 您以后可以加新的 modifier，定义新的动作序列。  
  这些架构在融合时都会保留；我们只是把底下依赖的“数学/控件小工具”换成您工程里的自写实现（方案 A），**不删掉、不锁死**表情和动画的扩展能力。

- **为何推荐方案 A（自己写 / 最小替代）**  
  - 您**完全掌控**这套小工具，以后加新表情、新动画时，不用迁就第三方库的 API 或版本。  
  - 新表情、新 modifier 仍然按 Stackchan 那套（skins、decorators、modifiers）加即可，和“用不用 smooth_ui_toolkit”无关。  
  - 方案 B 虽然移植快，但多一个外部依赖，您以后改表情/动画还要看那个库的接口，不利于您长期自己扩展。  

**实施时**：按方案 A，在 1.27-xiaozhi 内写一个小的 `stackchan_utils`（或类似命名），提供 Vector2i、clamp、map_range、简单插值/定时更新，以及按需对 LVGL 的薄封装；Stackchan 的 avatar/motion 只依赖这份实现，便于您后续随意加表情和动画。

---

### 2. 显示接口对接 — 写一层适配

已确认：**由实施时在 1.27-xiaozhi 内写一层薄适配**，让 StackChan 的显示（StackChanAvatarDisplay）能复用 1.27-xiaozhi 的 LvglDisplay/LvglTheme 等接口；若类名、主题名、字体有差异，只在这层适配里做桥接，不动您现有业务代码。

---

### 3. 刷新方式 — 该如何接？

**目标**：StackChan 的 `update()`（负责表情、舵机 modifier 的每帧更新）必须在**和 LVGL 刷新同一上下文**里调用，避免竞态（花屏、舵机乱动）。

**推荐接法**（实施时按此做）：

- 1.27-xiaozhi 里 LVGL 通常由 **lv_timer** 或 **显示刷新任务** 驱动（例如在某个定时器或任务里调 `lv_timer_handler()` / 显示 flush）。  
- 在 **stackchan 板型** 的显示初始化里（例如 `StackChanAvatarDisplay` 构造或首次显示时），**注册一个 LVGL 定时器**（`lv_timer_t`），周期与您当前 UI 刷新率一致或略低（例如 20–30 ms 一帧）。  
- 在该定时器的回调里**只做两件事**：  
  - 调用 `GetStackChan().update()`（更新表情与舵机 modifier）；  
  - 如需，再调一次 `lv_refr_now(nullptr)` 或由现有 LVGL 定时器统一刷新。  
- 这样 `StackChan.update()` 始终和 LVGL 在**同一线程、同一“帧”节奏**里执行，不会和显示刷新抢资源。  

若您当前工程里 LVGL 是在某个 FreeRTOS 任务里循环调 `lv_timer_handler()`，也可以在该任务的循环里、在 `lv_timer_handler()` **之后** 加一行 `GetStackChan().update()`（仅当板型为 stackchan 时编译），效果等价。  

**方案里会写明**：stackchan 板型下，StackChan 的 `update()` 通过上述方式与现有 LVGL 刷新接好，不修改 Application 主流程。

---

### 4. 官方主板 — 无需考虑

您使用官方 StackChan 主板，Flash/PSRAM 按官方配置即可，方案中不再单独列风险项。

---

### 5. 事件接口（OnImuEvent / OnHeadPetGesture）— 使用场景说明，供您确认是否要加

**这两个接口是干什么的**  
在 Application 里新增两个**可选回调**（或虚函数），默认空实现：  
- `OnImuEvent(ImuMotionEvent e)`：例如 `Shake`（晃动）、`PickUp`（被拿起）；  
- `OnHeadPetGesture(HeadPetGesture g)`：例如 `Press`（按下）、`Release`（松开）、`SwipeForward` / `SwipeBackward`（前/后滑动）。  

只有 **stackchan 板型** 在检测到 IMU/头触摸事件时才会去调它们；其它板型不编译、不调用。

**典型使用场景**

| 场景 | 说明 |
|------|------|
| **仅设备内反应** | 不实现这两个接口（保持空）：摸头、晃动仍可驱动 Stackchan 的 head_pet / imu modifier，表情和舵机会动，但**不**把事件上报给 Application / 云端 / APP。 |
| **上报到您的云端或 APP** | 在 `OnHeadPetGesture` 里：用户摸头时，通过您现有的协议（WebSocket/MQTT/MCP 等）发一条“摸头”事件到云端或 APP，例如用于统计、联动智能家居、在 APP 上显示“被摸头了”。在 `OnImuEvent` 里：设备被拿起或晃动时，上报“设备被移动/晃动”，用于防丢、场景联动等。 |
| **驱动小智逻辑** | 在 `OnImuEvent(PickUp)` 里：调用 `Application` 的“唤醒”或“开始聆听”，实现“拿起即说”。在 `OnHeadPetGesture(Press)` 里：触发一次播报或切换状态（例如“摸头就讲笑话”）。 |
| **MCP 或其它业务** | 在接口里把事件转成 MCP 工具调用或内部事件，由您现有 MCP/业务层处理。 |

**是否建议加**  
- 若您**只要**设备上的表情/动作（摸头就动、晃就动），**不**需要把事件传到云端或 APP，可以不实现这两个接口（保留空实现即可），融合时仍会加这两个“钩子”，不影响行为。  
- 若您**以后**可能要做“摸头/晃动上报、拿起即说、MCP 联动”等，建议**同意加这两个接口**，这样后续只需在接口里写您的逻辑，不用再改板级驱动。

您确认“要加”或“先加接口、实现暂时为空”后，方案里会写明：在 Application 中新增上述接口，默认空实现，仅 stackchan 板型调用。

---

### 6. NFC — 能干嘛？在 Stackchan 里有什么作用？再定本期做不做

**NFC 一般能干嘛**  
- 读/写 NFC 标签（例如贴一张标签，手机或设备碰一下就能读出一段信息、一个 URL、一段文本）。  
- 卡模拟（设备模拟成一张卡，被读卡器读）。  
- 两台设备碰一碰做配对或传小数据（P2P）。  

**在 Stackchan 产品里**  
- 官方介绍里写机身带“**full-featured NFC module**”，是**硬件上有 NFC 模块**。  
- 当前 **Stackchan 固件仓库里没有 NFC 驱动或业务逻辑**（已搜过，无 NFC 相关代码）；头触摸用的是 Si12T（三区电容），和 NFC 是两回事。  
- 因此可以推断：NFC 在 Stackchan 上**预留了硬件能力**，典型用途会是“**碰一下 NFC 标签触发某个动作**”（例如换人格、播一段话、跳转链接、触发舞蹈等），但**软件侧尚未在开源固件里实现**。

**对本期融合的影响**  
- 若本期**不做** NFC：不在 1.27-xiaozhi 里移植 NFC 驱动和业务，不影响表情、舵机、摄像头、IMU、头触摸等已定功能；等以后 Stackchan 或社区有 NFC 驱动/应用示例，再作为“后续扩展”加。  
- 若本期**要做** NFC：需要先查清官方 StackChan 用的 NFC 芯片型号与通信方式（I2C/SPI 等），再在 1.27-xiaozhi 的 stackchan 板型下加对应驱动与简单应用（例如读标签、回调给 Application），工作量会明显增加，且依赖硬件与文档。

**建议**  
先明确：您近期有没有“碰 NFC 标签控制设备”的需求？  
- **没有**：本期将 NFC 标为**后续扩展**，先不做。  
- **有**：再确认官方主板 NFC 芯片与接口，然后在本期或下一期按“后续扩展”任务加驱动与接口。

您已决定 NFC 本期不做、标为后续扩展，并已写入第八节。

---

## 方案定稿与执行约定

- **第八节**已汇总您的全部决定（板型名 stackchan、方案 A 自写库、显示适配、刷新接法、官方主板、引脚/文档位置、事件接口要加、NFC 不做、仅 stackchan 板型用表情/动作）。
- **第九节**已明确官方 PCB 是什么，以及融合完成后**引脚定义与焊接说明的位置**：`main/boards/stackchan/config.h` 与 `main/boards/stackchan/README.md`，便于焊接工作人员查阅。
- **请您审核本方案**；若无异议，审核通过后再按本方案执行代码修改。若有个别处需调节，指出后我们只改方案或实施细节，再执行。
