# 打断后监听与音频上行恢复修复

日期：2026-09-16。针对同一连接能发送 listen start、却没有后续 Opus 的固件侧缺口。

## 修复前状态

已有普通切换对话/唤醒打断后的恢复入口，以及无活动 TTS 时丢弃迟到音频的初步保护。
但这些处理尚不完整：

- TTS start 在主循环执行时才递增代次；网络线程提前收到的合法 stop/字幕可能被误认为过期。
- 排队中的下行音频没有绑定代次；直接从网络线程入解码队列也会绕过主循环的打断顺序。
- 已经处于 Listening 时，SetDeviceState 提前返回，不能修复实际停止的语音处理。
- 采集循环一次 ReadAudioData 失败就退出；这条任务只在启动时创建，再次唤醒不会重建。
- NoAudioProcessor 的 Feed 与 Stop 会同时操作 PCM 缓冲；原来的模式锁没有覆盖 Feed。

这些是源码可确认的缺陷；没有对应设备新串口日志，不能认定每一次现场故障都由同一条路径触发。

## 当前处理

1. 在收到 TTS start 时分配代次；start、audio、stop、字幕按主循环队列顺序处理。
   打断、通道清理和录入让位会使已排队的旧事件失效。音频本身不再切换 Speaking。
   待处理音频数量有上限，与现有解码队列容量一致，避免主循环忙时无限堆积。
2. 统一重新启用语音处理、恢复就绪门控、关闭唤醒检测并发送 listen start。
   已经 Listening 的唤醒/手动入口会检查真实处理状态，异常时重启处理；健康时不重复通知。
3. 采集读取失败后每 50 ms 重试并重新检查当前模式，只有显式停止服务才退出采集任务。
4. Feed 与 Start/Stop、上行代次重置使用同一模式锁；阻塞读取发生在锁外，读取完成后
   检查处理状态和代次，丢弃跨越停止/恢复过程的旧 PCM。
5. 全零 PCM 仍送入编码器，由编码器决定静音/DTX 输出，避免固件层提前吞掉所有静音帧。
6. `[WS_AUDIO_UP]` 新增 `read_ok/read_fail/processor/ready/wake`，配合已有
   `pcm_frames/encode_ok/enqueued/send_ok/send_fail/stale_drop` 定位流水线停在哪一段。

`AbortSpeaking()` 保持停止播放的职责。用户打断入口明确恢复监听；录入让位、提醒抢占
等调用方仍由各自流程决定下一步。修复不以重启设备或拆 WebSocket 作为恢复手段。

## 验证

- `tools/run_tts_interrupt_host_test.py` 提取当前生产函数及接收回调，在主机上注入事件及
  读取故障。10 组场景：同批 start/audio/stop、打断前排队事件和打断后迟到事件、
  新旧 TTS 交错、监听状态修复、录入及清理隔离、连续读失败恢复、跨模式读取丢弃、
  Feed/Stop 互斥、静音编码入队、接收队列上限。ASan/UBSan 启用。
- 63 项现有 WebSocket 相关回归检查。
- ESP32-S3 固件构建及应用分区容量检查。

以上检查本轮均通过。应用镜像保存于
`releases/tts-interrupt-recovery-20260916/xiaozhi.bin`，大小 `0x478b10` 字节，
5 MiB 应用分区剩余约 11%。它包含构建时工作区已有修改，包括前一轮发送超时修复。
SHA256：`8F75E89EBDA324C67DE37F01364699B9A2DAB81FC5E51CAF4C86F3C5AFF9FCF4`。

主机测试替代的是硬件/RTOS 接口；不等同于麦克风、WiFi 和云端的实机验收。
尚未烧录。v2 二进制音频没有对话轮次标识，因此不能识别服务器在一个真正的新 start
之后又混发的旧轮次数据；本修复保证本地已排队旧事件及新 start 之前的残留音频不关闭新监听。

## 实机验收

在 TTS 开头、中间、结尾分别唤醒打断/双击打断并立即说话，连续多轮重复。
观察同一 WebSocket 会话内 `listen_armed` 后 `processor=1 ready=1 wake=0`，
随后 `read_ok → pcm_frames → encode_ok → enqueued → send_ok` 持续增长；
服务端 `frames_after_listen_start` 应大于零。若再次出现零上行，保存同一时间段的
串口与服务端日志，依据新增计数定位，不能仅凭 listen start 判定麦克风已恢复。
