# 1.27-xiaozhi 与 Stack-chan 功能对照表

> **版本**: 1.0  
> **日期**: 2025-02  
> **目的**: 对比两个项目的功能实现，便于功能移植与参考选型。模块化 Mod 不纳入对比范围。

---

## 一、总体架构

| 维度 | 1.27-xiaozhi | Stack-chan |
|------|---------------|------------|
| **运行环境** | ESP-IDF (C/C++) | Moddable XS (JavaScript/TypeScript) |
| **平台** | 多款 ESP32 板型（esp-box-3、M5Stack、魔珐等） | M5Stack 系列（Core2/CoreS3/Atom S3 等） |
| **显示驱动** | esp_emote_gfx / LVGL / SPI LCD / OLED | Poco（Commodetto）/ LVGL 兼容 |
| **集成方式** | Board 选型 + Display 子类 | Mod 可选注入（本表不涉及 Mod 逻辑） |

---

## 二、显示与表情

### 2.1 显示类型

| 功能 | 1.27-xiaozhi | Stack-chan |
|------|---------------|------------|
| **EmoteDisplay** | esp_emote_gfx 管线，EAF 动画或程序化表情 | — |
| **LcdDisplay** | LVGL 全功能 UI、聊天、状态栏 | — |
| **StackChanAvatarDisplay** | main/stackchan LVGL Avatar（eyes + mouth + speech） | — |
| **Simple/Small/Dog Face** | — | 程序化矢量绘制，Commodetto path |

### 2.2 程序化表情对照

| 特性 | 1.27-xiaozhi (procedural_emote) | Stack-chan (simple-face + modifier) |
|------|----------------------------------|------------------------------------|
| **眼睛** | 实心圆 fill_circle | path.arc(cx, cy, radius, 0, 2π) |
| **眼皮形状** | 矩形遮罩，由 eye_weight 控制高度 | 按 emotion：矩形/梯形/双矩形（ANGRY/SAD/HAPPY/SLEEPY） |
| **嘴巴** | fill_rounded_rect，w/h 与 open 反比 | path.rect，w=90→50、h=6→58 |
| **嘴型公式** | w = 90 - 40×open, h = 6 + 52×open | w = minW+(maxW-minW)*(1-open), h = minH+(maxH-minH)*open |
| **眨眼** | linearInEaseOut，openMin 4s / closeMin 0.2s | 同逻辑 |
| **呼吸** | sin(2π*t/6000)，整脸偏移 | face.breath = quantize(sin(...), 8) |
| **Saccade（眼动）** | ❌ 未实现 | ✅ normRand，gain 0.2，300–2000ms 更新 |
| **视线 gazeX/Y** | ❌ 无 | ✅ 眼睛可偏移，配合 lookAt |
| **表情 emotion** | neutral/happy/angry/sad/doubt/sleepy | NEUTRAL/HAPPY/SAD/ANGRY/SURPRISED/SLEEPY/DOUBTFUL |

### 2.3 表情 emotion 映射

| 1.27-xiaozhi | Stack-chan | 眼开合 eye_weight |
|--------------|------------|-------------------|
| neutral | NEUTRAL | 100（全开） |
| happy | HAPPY | 72 |
| angry | ANGRY | 70 |
| sad | SAD | 70 |
| doubt | DOUBTFUL | 75 |
| sleepy | SLEEPY | 35 |

---

## 三、Display 接口（1.27-xiaozhi）与 Robot API（Stack-chan）

| 1.27-xiaozhi Display | Stack-chan Robot | 说明 |
|---------------------|------------------|------|
| `SetEmotion(emotion)` | `setEmotion(emotion)` | 设置表情 |
| `SetStatus(status)` | — | 状态文字（LISTENING/STANDBY 等） |
| `SetChatMessage(role, content)` | `showBalloon(text)` | 聊天/气泡文字 |
| `ShowNotification(msg, dur)` | — | Toast 通知 |
| `ShowQrCode(content)` | — | 配网二维码 |
| `SetPowerSaveMode(on)` | `pause()` / `resume()` | 省电/暂停 |
| — | `say(text)` | TTS 朗读 |
| — | `lookAt([x,y,z])` | 视线看向空间点 |
| — | `lookAway()` | 取消注视 |
| — | `setPose(pose)` | 舵机姿态 |
| — | `setTorque(on)` | 舵机使能 |
| — | `setColor(primary/secondary, r,g,b)` | 主题色 |
| — | `record()` | 麦克风录音 |
| — | `tone(hz, dur)` | 蜂鸣 |

---

## 四、TTS 与嘴型

| 特性 | 1.27-xiaozhi | Stack-chan |
|------|--------------|------------|
| **TTS 引擎** | 晓智云端/本地（协议层） | Local / Remote / VoiceVox / ElevenLabs / OpenAI |
| **嘴型同步** | ❌ 未按音量驱动 mouth.open | ✅ TTS.onPlayed(volume) → mouthOpen = min(volume/2000, 1) |
| **TTS 完成** | — | TTS.onDone → mouthOpen = 0 |

---

## 五、舵机与运动

| 特性 | 1.27-xiaozhi | Stack-chan |
|------|--------------|------------|
| **舵机** | esp-box-3 无舵机（仅屏） | SCServo / RS30X / PWM / Dynamixel / None |
| **头部运动** | — | `applyRotation(ori, time)` |
| **视线跟随** | — | `lookAt` + `updatePose` 计算 yaw/pitch |
| **姿态查询** | — | `getRotation()` |

---

## 六、输入设备

| 特性 | 1.27-xiaozhi | Stack-chan |
|------|--------------|------------|
| **按键 A/B/C** | 板级定义，回调各异 | 统一 `robot.button.a/b/c.onChanged` |
| **触摸屏** | 部分板型支持 | Touch 实例，可选 |
| **麦克风** | 语音识别流程 | `robot.record()` 暴露 |

---

## 七、配网与网络

| 特性 | 1.27-xiaozhi | Stack-chan |
|------|--------------|------------|
| **WiFi 配网** | BLE 配网 + 二维码（ShowQrCode） | config_wifi Mod：BLE PreferenceServer |
| **二维码** | EmoteDisplay：qrcodegen；LcdDisplay：lv_qrcode | — |

---

## 八、可参考移植的功能（不含 Mod）

| 功能 | Stack-chan 来源 | 1.27-xiaozhi 现状 | 建议 |
|------|----------------|-------------------|------|
| **Saccade 眼动** | modifier.ts | 未实现 | 在 procedural_emote 中加随机 gazeX/Y |
| **情绪化眼皮形状** | simple-face createEyelidPart | 矩形眼皮 | 参考 ANGRY/SAD/SLEEPY/HAPPY 的梯形/双矩形 |
| **嘴型随 TTS** | robot.ts useTTS.onPlayed | 未实现 | 音频回调驱动 mouth.open |
| **lookAt 视线逻辑** | robot.ts updatePose | 无舵机场景不适用 | 若有舵机可参考 yaw/pitch 计算 |
| **按键语义** | default-mods A=张望 B=动作 C=换色 | 板级各自实现 | 可统一按键语义设计 |
| **pause/resume** | robot.ts | SetPowerSaveMode 类似 | 已覆盖 |

---

## 九、参考文件索引

### Stack-chan（程序化表情与核心逻辑）

| 文件 | 内容 |
|------|------|
| `stackchan/renderers/simple-face.ts` | 眼睛/眼皮/嘴的绘制、坐标、emotion 眼睑形状 |
| `stackchan/renderers/modifier.ts` | 眨眼 linearInEaseOut、呼吸 sin、Saccade normRand |
| `stackchan/renderers/renderer-base.ts` | FaceContext、Layer 分层 |
| `stackchan/robot.ts` | useTTS.onPlayed 嘴型、lookAt、setEmotion |

### 1.27-xiaozhi（程序化表情与集成）

| 文件 | 内容 |
|------|------|
| `main/display/procedural_emote.cc/h` | 程序化绘制核心 |
| `main/display/emote_display.cc` | EmoteDisplay 集成、timer、SetEmotion |
| `docs/STACKCHAN_PROCEDURAL_EMOTE_PLAN.md` | 程序化表情方案与参考说明 |

---

## 十、总结

- **1.27-xiaozhi**：面向晓智语音助手，多板型、多显示类型（Emote/LCD/OLED），重点在聊天、状态、配网、程序化表情。
- **Stack-chan**：面向桌面机器人，强调舵机、视线、程序化表情、TTS 嘴型同步，通过 Mod 扩展能力。

**建议优先参考**：Saccade 眼动、情绪化眼皮形状、TTS 嘴型同步；三者均可在 1.27-xiaozhi 的 procedural_emote 与 Display 层内实现，无需引入 Mod 架构。
