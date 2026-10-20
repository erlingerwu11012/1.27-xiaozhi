# 卡片语音操作

## 正式路由（唯一）

```
reminder.get_current → reminder.action(instance_id, revision, action)
```

服务端不再因能力缺失、业务失败、无卡、revision 冲突或权限失败而降级到 `card.*`。

## 旧版 card.*

- 设备 `tools/list` 仍可能上报 `card.get_current` / `card.action`（固件暂不改）。
- 模型 Function Calling tools **不暴露** `card_get_current` / `card_action`。
- 若仍被调用，服务端拦截并要求改用 `reminder_*`。

## 能力探测

- `available_tools` / `name_mapping` 含 `reminder.get_current` + `reminder.action`（或 sanitized 名）→ 可走语音路由。
- 仅含 `card.*` → 语音路由返回无能力（不再调用 card）。

## 挂接点

`receiveAudioHandle.startToChat`：ASR 文本入口在 LLM 意图前拦截卡片口令；不在 `intentHandler` / `unified_tool_manager` 重复挂接。

映射：完成→primary，稍后→secondary，不需要了/取消→tertiary。

实现：`core/utils/card_action.py` 的 `route_card_voice_action`。

`reminder_action` 须使用最近一次 `reminder_get_current` 的 `instance_id` + `revision`（>0）；空 ID / revision=0 / 不匹配均不下发设备。

## 可观测性

卡片动作经 `reminder_audit` 记录 `card_action_get_current` / `card_action_execute`（含 `tool_family`、`correlation_id`，不落敏感正文）。
