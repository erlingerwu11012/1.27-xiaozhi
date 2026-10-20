# 音频上行短暂超时导致主连接关闭：修复说明

## 已确认的触发链

2026-09-15 的日志中，设备 `ac:a7:04:fd:20:2c` 在 TTS 后恢复监听。
服务端 17:34:41 记录 ASR 开始，17:34:44 异常断开，最后音频帧仅在 2 ms 前到达。
固件同时记录：

```text
68822 transport_poll_write(0)
68861 DISCONNECTED connected=0
68966 requested_bytes=130 returned_bytes=0 elapsed_ms=646 transient=0
68980 audio_send_fatal
69005 Closing websocket audio channel
```

本次是整帧写入前的可写等待超时被底层库升级为断线。上层随后才销毁连接，
并没有等待累计四次失败。日志中的弱信号可能促成拥塞，但不能据此确定网络拥塞源。

## 修复行为

1. 传输层用独立返回值标记“帧头尚未写入”的超时；帧头/负载部分写入仍是故障。
2. WebSocket 客户端对**未开始**的完整 text/binary 消息保留连接，并区分两类码：
   - `-2` `ESP_WEBSOCKET_CLIENT_SEND_NOT_STARTED`：帧头前 poll 超时（socket 不可写）
   - `-3` `ESP_WEBSOCKET_CLIENT_SEND_TX_LOCK_TIMEOUT`：发送锁获取超时  
   二者均为“消息未开始”，可丢单帧音频；**不要再写成“所有临时失败都是 -2”**。
   已发出前序分片或负载部分写入后仍中止（fatal）。
3. 音频协议层将上述未开始超时视为丢一个包，取消连续次数触发拆连接的策略。
   次数仅用于限频日志，发送成功后清零。底层真实故障及既有心跳机制仍保留。
4. 上行音频按采集时间计算，超过 1.5 秒的包出队时丢弃，限制恢复后的陈旧语音。
   时间戳为本地字段，不改变 v1/v2/v3 的线上格式。唤醒预录包的零时间戳保持原有行为。
5. 致命发送失败在等待连接销毁前停止语音处理、清理上行队列；编码任务入队时
   再检查上传代次，防止旧任务把队列重新填回去。
6. 本地检测到说话即刷新监听活动，不再依赖这一帧是否发送成功。
7. 修正错误事件未初始化的诊断字段，以及读轮询后未检查连接已关闭的竞态。

`esp_websocket_client` 作为项目内组件固定在 1.7.0，并通过 `override_path` 引用。
已有 `tcp_transport` 项目组件与其配套，重建不会换回未修复的托管客户端。

诊断日志应出现 `fail_class=socket_not_writable` 或 `fail_class=tx_lock_timeout`，
以及 `action=drop_packet_keep_link`、`transient=1`；不得仅凭 `returned_bytes=-2`
把锁超时与 socket 不可写混为一谈。

## 验证方法

- `python3 tools/run_ws_audio_send_host_test.py`：实际生产发送函数的主机故障注入，
  ASan/UBSan 遇错失败；覆盖两种 TX 锁配置、v1/v2/v3、连续 25 次超时后成功恢复、
  锁超时（`-3`）、socket 不可写（`-2`）、部分写入、分片中途失败、空消息、断开/空连接、过期音频出队。
- `python -m unittest discover -s tools -p '*ws*regression_test.py'`：相关已有集成约束。
- ESP-IDF 构建及分区容量检查。硬件弱网复现仍需烧录后的串口与服务端配对日志。

修复后的安全超时应看到 `action=drop_packet_keep_link`、`transient=1` 与明确的 `fail_class`，
恢复后同一会话继续有上行帧，而非紧接着出现 `audio_send_fatal`/`local_close`。
丢弃的音频不能恢复，本修复保证的目标是短暂拥塞不主动结束整场对话。

### 本轮验证结果（2026-09-16）

- 两种锁配置的实际函数故障注入通过，ASan/UBSan 无错误。
- 63 项相关回归检查通过。
- ESP32-S3 固件构建通过，应用大小 `0x4787f0` 字节，5 MiB 应用分区剩余约 11%。
- 独立应用固件副本：`releases/ws-audio-timeout-20260916/xiaozhi.bin`。
  这是应用镜像，不是合并烧录镜像；包含构建时工作区既有修改。尚未烧录或实机弱网验收。

## 与“打断后无上行”的区别

连接可继续发送 `listen start`，但 `frames_after_listen_start=0`，是另一类
音频生产/监听状态恢复问题。本补丁不更改 TTS 打断、迟到下行音频和恢复监听策略。
尤其需要区分 `AbortSpeaking()` 自身与调用它之后会恢复监听的调用方，不能仅凭
该函数没有设置 Listening，就断定所有打断入口都无法恢复。
