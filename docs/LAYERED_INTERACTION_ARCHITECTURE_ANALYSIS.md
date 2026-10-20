# 分层式交互架构分析报告

## 一、总体结论

当前代码库**具备分层式交互架构的雏形**，但三层边界不清晰：**反应层**与**行为层**混在板级/手势/主循环中，**认知层**通过 `Schedule` 与主事件循环串行化，避免了“等大模型返回才动”的阻塞，但**启动阶段存在明显阻塞**，且大量逻辑**硬编码**在 `Application` 与 `GestureHandler` 中。

---

## 二、三层归属与现状

### 2.1 反应层（Reaction Layer）

**定义**：传感器/电机等毫秒级实时响应，硬编码有限状态机，不依赖云端。

| 模块 | 位置 | 归属判断 | 说明 |
|------|------|----------|------|
| **TouchManager** | `main/touch/touch_manager.cc` | ✅ 反应层 | 独立任务轮询 I2C 触摸，产出原始 touch 事件 |
| **GestureEngine** | `main/touch/gesture_engine.cc` | ✅ 反应层 | 基于时间戳的 FSM（IDLE/PRESSED/MOVING），识别 TAP/长按/滑动/画圈，**非阻塞**，由 33ms 定时器驱动 |
| **AudioService 输入/输出/编解码任务** | `main/audio/audio_service.cc` | ✅ 反应层 | 多任务 + 队列，唤醒词检测、VAD、编解码均在独立任务，通过 `xEventGroupSetBits` 通知主循环，不阻塞 |
| **ESP-BOX-3 手势定时器** | `main/boards/esp-box-3/esp_box3_board.cc` | ✅ 反应层 | `gesture_engine_.Update(now_ms)` 每 33ms 调用，驱动手势识别 |

**缺失/问题**：

- 反应层**没有独立“反射动作”出口**：手势识别后直接进入 `GestureHandler::OnGesture()`，其中既做“摸头→开心”的**本地行为**，又调用 `TryHandleLlmTouch()` 发 MCP 进**认知层**，导致“反射”与“认知”耦合在同一处。
- 电机/舵机：仅 StackChan 板型有 `stackchan::motion`，其他板型无统一反应层执行器抽象。

---

### 2.2 行为层（Behavior Layer）

**定义**：自主行为、情感状态机、空闲微动，由本地逻辑触发，可独立于云端运行。

| 模块 | 位置 | 归属判断 | 说明 |
|------|------|----------|------|
| **DeviceState + 状态切换时的 UI/音频** | `application.cc` `SetDeviceState()` | ⚠️ 行为/认知混合 | Idle→Listening→Speaking 的切换、SetStatus/SetEmotion/SetChatMessage 均在主循环内；状态既由云端 JSON 驱动，也由本地超时/触摸驱动 |
| **聆听超时 / 期待状态超时** | `application.cc` `MAIN_EVENT_CLOCK_TICK` | ✅ 行为层 | 纯本地逻辑：`listening_start_tick_` + `listening_timeout_ms_`，超时后 `Schedule(CloseAudioChannel; SetDeviceState(Idle))`，非阻塞 |
| **GestureHandler 表情/音量/主题** | `main/touch/gesture_handler.cc` | ⚠️ 行为+认知 | 摸头开心、摸脸害羞、滑动调音量、双击唤醒、画圈头晕等：**表情与气泡文案是行为**；**TryHandleLlmTouch 是认知**，二者同在一个 switch 里 |
| **emotion_reset 定时器** | `gesture_handler.cc` | ✅ 行为层 | 若干秒后 `SetEmotion("neutral")`，本地定时，不依赖云端 |
| **StackChan modifiers** | `main/stackchan/` | ✅ 行为层 | blink、breath、idle_motion、dance 等，由 StackChan 自己的 update 驱动，与主循环解耦 |
| **状态栏/时钟更新** | `MainEventLoop` `clock_ticks_` | ✅ 行为层 | `display->UpdateStatusBar()`、心跳 ping，本地周期逻辑 |

**缺失/问题**：

- **没有独立“行为状态机”**：情感/空闲行为分散在 `SetDeviceState`、`GestureHandler`、`Display` 中，缺少统一的“当前行为模式”（如 idle_curious / idle_sleepy / reacting_to_touch）及其与表情/微动的映射。
- **表情名、提示语、超时时间**多为硬编码（如 `BALLOON_HEAD_PET_HAPPY`、`LISTENING_TIMEOUT_MS`、`EXPECTATION_TIMEOUT_MS`），不可配置。

---

### 2.3 认知层（Cognitive Layer）

**定义**：对接云端大模型（LLM），通过 Function Calling / 结构化输出指挥底层动作。

| 模块 | 位置 | 归属判断 | 说明 |
|------|------|----------|------|
| **Protocol (WebSocket/MQTT)** | `main/protocols/` | ✅ 认知层 | 收发 JSON/二进制，`OnIncomingJson` 在**网络回调线程**中执行 |
| **OnIncomingJson 分支** | `application.cc` | ✅ 认知层 | 解析 `tts`/`stt`/`llm`/`alert`/`error`/`mcp`/`listen` 等，**全部通过 `Schedule(callback)` 投递到主事件循环**，不在网络线程改 UI/状态 |
| **MCP / touch_prompt** | `gesture_handler.cc` + `application.cc` | ✅ 认知层 | 触摸触发 `SendMcpMessage(touch_prompt)`，云端可据此生成回复；MCP 解析在 `McpServer::ParseMessage` |

**重要结论**：

- **没有出现“大模型未返回，机器人就死机/停止运动”的阻塞**：云端 JSON 到达后只做轻量解析并 `Schedule(...)`，主循环按事件顺序执行；TTS/STT/emotion 均由主循环内的 task 执行，不阻塞网络或音频线程。
- **潜在风险点**：若某次 `Schedule` 的 callback 内部出现长时间阻塞（如当前代码中**未见**在 Schedule 里做同步 HTTP/等待 LLM），则只会阻塞主事件循环，不会阻塞触摸/音频等反应层任务；但**启动阶段**（见下）是例外。

---

## 三、架构冲突与阻塞点

### 3.1 启动阶段阻塞（严重）

以下逻辑在 **`Application::Start()`** 中**顺序执行**，且运行在 **app_main 线程**（即主任务），会阻塞直到完成或超时：

| 位置 | 行为 | 影响 |
|------|------|------|
| `CheckAssetsVersion()` | `vTaskDelay(3000)`；`assets.Download(...)` **同步下载**整包资源；`assets.Apply()` 解析并加载 | 网络慢或资源大时，开机后数十秒无响应，**触摸/显示仍可更新**（因 MainEventLoop 在另一任务），但**无法进入 Idle/Listening**，因协议尚未初始化 |
| `CheckNewVersion(ota)` | `while(true)` 内：版本检查、激活码、`ota.Activate()` 重试，`vTaskDelay(3000/10000)` | 激活失败或网络异常时，**长时间阻塞 app_main**，用户无法使用设备 |
| `board.StartNetwork()` | 等待 WiFi 连接 | 依赖具体实现，通常有超时，但仍会阻塞 |

**结论**：**认知层依赖**（网络、OTA、资源）在启动时以**同步方式**执行，导致“机器人未就绪前无法交互”；反应层（触摸、音频任务）已运行，但**行为层/认知层未就绪**，整体表现为“开机卡住”。

### 3.2 主事件循环单线程串行

- `MainEventLoop` 是**单线程**：所有 `Schedule` 的 callback、状态机、发送音频、处理时钟都在同一任务中顺序执行。
- **优点**：无竞态，状态一致性好。
- **缺点**：若某个 callback 耗时过长（例如未来在 Schedule 里调用了同步 HTTP），会推迟聆听超时、状态栏更新、下一次触摸响应等。

### 3.3 手势与 LLM 的紧耦合

- `TryHandleLlmTouch()` 在**同一手势分支**里既更新表情/气泡（行为），又发送 MCP prompt（认知），且**节流**（500ms）写死在函数内。
- 若云端不返回或 MCP 未配置，设备仍会进入 Listening 并重置超时；**不会死机**，但“摸头/摸脸”的**本地反馈**与“云端回复”强绑定，无法单独关闭云端而保留本地表情。

---

## 四、硬编码 vs 可配置

### 4.1 硬编码（紧耦合）

| 内容 | 位置 | 说明 |
|------|------|------|
| 设备状态机分支（Idle/Listening/Speaking 的 UI、音频开关） | `application.cc` `SetDeviceState()` | switch 写死每种状态的 display/audio 行为 |
| 手势 → 表情/文案/LLM prompt | `gesture_handler.cc` `OnGesture()` | 摸头=开心+固定 prompt，摸脸=害羞+固定 prompt，滑动=生气/晕+固定 prompt |
| 表情名、提示语 | `gesture_handler.cc` | `BALLOON_HEAD_PET_HAPPY`、`BALLOON_RUB_FACE` 等 |
| 超时时间 | `application.h` / `application.cc` | `LISTENING_TIMEOUT_MS`、`EXPECTATION_TIMEOUT_MS`、`EXPECTATION_TIMEOUT_QUESTION_MS` |
| TTS 结束后的“期待状态”逻辑 | `application.cc` OnIncomingJson `tts/stop` | 是否进入 Listening、问号延长等，写死在 JSON 分支 |
| 错误/告警时的表情与提示 | `application.cc` Alert、MAIN_EVENT_ERROR | "sad"、OGG_EXCLAMATION 等 |

### 4.2 可配置（解耦）

| 内容 | 位置 | 说明 |
|------|------|------|
| 主题（light/dark）、字体、背景色 | `assets` index.json + `LvglThemeManager` | 通过资源分区配置 |
| 表情资源（GIF/图） | `assets` index.json `emoji_collection` | 名称与文件路径可配置 |
| 协议 URL/Token、MQTT/WebSocket | `Settings` NVS + OTA 下发的 config | 运行时可改 |
| 显示布局、图标 | `assets` index.json `layout` / `icon_collection` | Emote 模式下可用 |

---

## 五、架构重构建议清单

### 5.1 明确反应层（Reaction Layer）

| 建议 | 说明 |
|------|------|
| **抽离“反射动作”接口** | 定义 `ReactionHandler` 或类似接口：输入为 `GestureEvent` / 原始 touch，输出仅为**本地反射**（如亮灯、固定表情、蜂鸣），**不**调用 Protocol/MCP。GestureEngine 识别后先调 ReactionHandler，再由上层决定是否上报认知层。 |
| **手势到反射的映射可配置** | 将“TAP+HEAD → 开心+短音”等映射放到配置文件或 assets，板级或运行时加载，而不是在 `GestureHandler` 里 switch 写死。 |
| **统一电机/舵机抽象** | 若有多板型需要“反应层动作”，可增加 `MotionReaction` 接口（如立即转向、小幅度摆动），由反应层定时器或事件驱动，与认知层指令区分。 |

### 5.2 独立行为层（Behavior Layer）

| 建议 | 说明 |
|------|------|
| **引入行为状态机** | 将“当前行为模式”从 `DeviceState` 中拆出或扩展：如 `idle` / `listening` / `speaking` / `idle_expecting_reply`，以及纯本地的 `reacting_to_touch` / `showing_notification`。表情、空闲动画、超时由**行为状态**驱动，而不是在 Application 的多个分支里重复 SetEmotion。 |
| **情感/表情映射表** | 行为状态 + 可选“触发源”（触摸区域、云端 emotion 字段）→ 表情名 + 持续时间；表可由 JSON 配置，便于 A/B 或产品定制。 |
| **聆听/期待超时入配置** | `LISTENING_TIMEOUT_MS`、`EXPECTATION_TIMEOUT_MS` 等放入 NVS 或 assets，避免改代码才能调参。 |
| **本地提示语文案配置化** | 摸头/摸脸/画圈等气泡文案放入 `lang_config` 或 assets，与手势解耦。 |

### 5.3 认知层与解耦

| 建议 | 说明 |
|------|------|
| **保持 JSON → Schedule 的边界** | 继续保持“网络回调只解析 + Schedule，主循环执行状态/UI/音频”，避免在 Protocol 回调里直接调 Display/Application 成员。 |
| **MCP / touch_prompt 可选** | 通过配置或编译选项关闭“触摸时发送 MCP”，仅保留本地表情/音效，便于离线或弱网场景。 |
| **启动流程异步化** | 将 `CheckAssetsVersion`、`CheckNewVersion` 移出 app_main 顺序流程：在 MainEventLoop 或独立“Bootstrap”任务中执行，通过状态（如 kDeviceStateConfiguring）和事件驱动；资源下载用已有进度回调更新 UI，避免 `vTaskDelay` 长时间占住主任务。 |

### 5.4 代码迁移参考（按层归类）

| 当前位置 | 建议归属 | 说明 |
|----------|----------|------|
| `GestureEngine::Update`、TouchManager 任务 | **反应层** | 保持为底层输入，仅输出“事件”，不执行业务。 |
| `GestureHandler::OnGesture` 中“仅表情+气泡+音效”部分 | **行为层** | 拆到 `BehaviorLayer::OnGestureReaction()` 或类似，由配置表驱动表情/文案。 |
| `GestureHandler::OnGesture` 中 `TryHandleLlmTouch`、MCP 发送 | **认知层** | 保留在“认知入口”（如 Application 或 Protocol 相关），由“是否启用云端触摸”配置决定是否调用。 |
| `SetDeviceState` 内 display/audio 分支 | **行为层** | 可抽成 `BehaviorLayer::OnDeviceStateChange(prev, next)`，内部查表决定 SetEmotion/SetStatus 等。 |
| `OnIncomingJson` 各 type 分支 | **认知层** | 保持；仅将“设置表情/状态”委托给行为层接口，而不是直接 `display->SetEmotion`。 |
| 聆听/期待超时、emotion_reset 定时器 | **行为层** | 可归属到“行为层定时器”或统一 Idle 行为模块。 |
| StackChan modifiers（blink/breath/idle_motion） | **行为层** | 已是独立模块，仅需在文档/接口上明确为“行为层”。 |
| Protocol 收发、MCP、SendText/SendAudio | **认知层** | 保持；不直接依赖具体 Display 实现。 |

---

## 六、小结

- **反应层**：触摸与手势识别、音频前后端已接近“毫秒级、非阻塞”，但缺少独立的反射出口和可配置的反射映射。
- **行为层**：情感、超时、部分手势反馈具备行为特征，但分散且多硬编码，缺少统一行为状态机和配置化映射。
- **认知层**：云端 JSON 通过 Schedule 与主循环交互，**无“等大模型返回才动”的阻塞**；启动阶段同步下载/OTA 是主要阻塞来源。
- **重构优先级建议**：  
  1）启动异步化，减少开机阻塞；  
  2）手势→反射与手势→认知解耦，并配置化反射与文案；  
  3）引入行为状态机与情感映射表，使表情/提示由行为层统一驱动。
