# reminder_event 交互生命周期

## 180 秒卡片窗口

以**服务端收到** `interaction_opened` 的时刻记为 `received_at`（Unix 秒）。

- 实际 deadline：`min(请求的 expires_at, received_at + 180)`
- `expires_at ≤ received_at` → 拒绝（`interaction_expired`）
- `expires_at > received_at + 180` → **安全裁剪**至 `received_at + 180`（审计字段 `expires_at_clipped=1`）
- 到 deadline 后即使无 ASR/音频事件，服务端主动 `close_interaction` 并恢复普通 listen/idle 策略

## interaction_opened

```json
{
  "type": "reminder_event",
  "event": "interaction_opened",
  "instance_id": "note:7:abc",
  "revision": 3,
  "expires_at": 1234567890
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| instance_id | string | 当前卡片实例 ID |
| revision | int ≥0 | 卡片修订号 |
| expires_at | int | Unix 秒；须在 `(received_at, received_at+180]` 内，超出则裁剪 |

## interaction_closed

```json
{
  "type": "reminder_event",
  "event": "interaction_closed",
  "reason": "resolved"
}
```

| reason | 含义 |
|---|---|
| resolved | 用户完成操作 |
| timeout | 等待超时（含服务端 deadline 到期） |
| presence_lost | 用户离开 |
| preempted | 被更高优先级抢占 / 连接 superseded |

## 旧固件降级

- **不发** `interaction_opened` / `interaction_closed` → 服务端行为与改造前完全一致（不抑制 listen:stop、不延长 idle）
- 不发上述事件时，**不存在** 180 秒卡片窗口

## 固件同步清单

1. 卡片展示并等待语音操作 → 发送 `interaction_opened`（含 `instance_id`, `revision`, `expires_at`）
2. `expires_at` 建议设为「展示时刻 + 期望等待秒数」，但不得超过服务端 `received_at + 180`
3. 操作完成 → `interaction_closed` reason=`resolved`
4. 等待超时 → reason=`timeout`
5. 用户离开 → reason=`presence_lost`
6. 被抢占 → reason=`preempted`
