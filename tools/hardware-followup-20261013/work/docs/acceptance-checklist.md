# 验收清单（13 场景）

| # | 场景 | 覆盖测试 |
|---|------|----------|
| 1 | 隐私模式 `privacy_safe_required` 不进 LLM | `test_reminder_voice.TestPrivacySafe*` |
| 2 | 多项/错过话术 `pending_count` / `missed_occurrence` | `test_reminder_voice.TestPending*` |
| 3 | 提醒语音资产生成与 HTTPS 签名下发 | `test_reminder_voice.TestReminderVoicePipeline.test_asset_sent_on_success` |
| 4 | 卡片语音 primary/secondary/tertiary 映射 | `test_card_action.TestCardActionMapping` |
| 5 | reminder 路由成功 + revision 乐观锁冲突 | `test_card_action.test_success_primary` / `test_version_conflict` |
| 6 | reminder 能力缺失不降级 card；仅 card 设备返回无能力 | `test_card_action.TestCardActionDualRouting` |
| 7 | TTS start → sentence_start → stop 字幕时序 | `test_tts_subtitle` |
| 8 | interaction 180s 窗口（合法/裁剪/主动到期） | `test_reminder_interaction` |
| 9 | interaction 期间抑制 listen:stop | `test_interaction_lifecycle_regression.TestInteractionListenStopSuppression` |
| 10 | interaction 期间抑制 idle 断连 | `test_interaction_lifecycle_regression.TestInteractionIdleCloseSuppression` |
| 11 | interaction_closed 四种 reason 恢复 | `test_interaction_lifecycle_regression.TestInteractionCloseReasons` |
| 12 | 普通 abort 不删 ReminderVoiceStore 资产 | `test_reminder_voice_abort.TestAbortDoesNotDeleteStore` |
| 13 | 取消/代际 supersede 丢弃未下发资产 | `test_reminder_voice_abort.TestCancelDiscardsPendingAsset` / `TestSupersedeDiscardsPending` |

## 运行命令（单文件、60s 超时、日志落 /tmp）

```bash
cd /root/prjs/xiaozhi-esp32-server/main/xiaozhi-server
PY=/root/miniconda3/envs/xiaozhi-esp32-server/bin/python
for t in test_card_action test_reminder_card_converge test_interaction_lifecycle_regression test_reminder_voice_abort \
  test_reminder_interaction test_reminder_voice test_tts_subtitle; do
  timeout --signal=INT --kill-after=10s 60s $PY -m unittest test.$t \
    > /tmp/${t}.log 2>&1 || exit 1
done
```
