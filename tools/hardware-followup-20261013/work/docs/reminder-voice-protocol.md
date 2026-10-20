# 提醒语音协议

## reminder_voice_request（设备 → 服务端）

| 字段 | 类型 | 可选 | 说明 |
|---|---|---|---|
| instance_id | string | 必填 | 实例 ID |
| revision | int | 必填 | 修订号（回显） |
| voice_revision | int | 必填 | 语音修订号 |
| recipient_person_id | string | 必填 | usr_* |
| presence_generation | int | 必填 | 在场代际 |
| title / detail / constraints | string | 可选 | 话术输入 |
| **privacy_safe_required** | bool | 可选 | `true` 时永不调用 LLM，仅 `privacy_safe_text` 或本地兜底 |
| **privacy_safe_text** | string | 可选 | 隐私安全文案；`privacy_safe_required=true` 时使用 |
| **pending_count** | int | 可选 | ≥1 普通整数，默认 1；拒绝 bool/0/负数 |
| **announce_pending_count** | bool | 可选 | 是否在话术中表示多项待办 |
| **missed_occurrence** | bool | 可选 | 错过回顾（alarm 用平静闹钟文案） |
| source_type | string | 可选 | note/alarm 等，默认 note |
| phase | string | 可选 | due/followup 等 |

### 旧固件降级（无上述新字段）

| 字段 | 降级行为 |
|---|---|
| privacy_safe_required | 视为 false，可走 LLM |
| privacy_safe_text | 忽略 |
| pending_count | 默认 1 |
| announce_pending_count | 视为 false |
| missed_occurrence | 视为 false |

## reminder_voice_asset（服务端 → 设备）

必填：instance_id, voice_revision, phase, script, url, sha256(小写hex64), format=ogg_opus, bytes(1..16384)

## 话术优先级

1. privacy_safe_required → 不进 LLM
2. pending_count>1 && announce_pending_count && missed_occurrence → 确定性组合句
3. missed_occurrence only → 平静回顾
4. pending 前缀 + LLM / 单项 LLM

## 固件同步清单（提醒语音）

- 发送 `reminder_voice_request` 时按需携带上述 5 个新字段
- 接收 `reminder_voice_asset` 时校验 sha256 小写 hex64、format=ogg_opus、bytes 1..16384
- 旧固件省略新字段 → 服务端按上表降级，协议兼容

## 相关：卡片交互 180 秒窗口

见 [reminder-event-lifecycle.md](./reminder-event-lifecycle.md)。卡片语音操作与 `interaction_opened/closed` 配合使用；旧固件无 180 秒窗口。
