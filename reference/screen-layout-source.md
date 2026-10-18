# 当前本地程序的屏幕布局摘录
仅复制角色尺寸、位置、桌面遮挡相关片段，不包含网络、账号和对话记录。
来源：产品仓库 main/display/cubicat_home_player.cc，本地工作副本，2026-10-19。
这些是源码依据，不代表本轮已刷机验收。

```cpp
// Latest nvhai export already has 1.3x scale in its upper "bone".
// Do not apply the previous additional 1.3x display scale again.
// Reference right coat/table junction: screen (273,268).
// The latest sleeve pose differs from the old parent-scale-only estimate.
// Photo calibration (2026-10-13): move left 5 px and screen-up 3 px.
// Cubicat world Y points up: node origin (170.764,42.510) on 320x320.
// Keep the authored size; confirm the contact point after flashing.
constexpr float kSpineDisplayScale = 1.0f;
constexpr float kSpinePositionOffsetX = 10.764f;
constexpr float kSpinePositionOffsetY = 2.510f;
```

```cpp
                } else {
                    LogHomeInitStage("spine_skeleton_ready");
                    spine->setScale(cubicat::Vector2f(
                        kSpineDisplayScale, kSpineDisplayScale));
                    spine->setSkinByName(meta.skin.c_str());
                    LogHomeInitStage("spine_skin_ready");
                    if (meta.role_id == "nvhai_builtin") {
                        const bool overlay_ready = spine->prepareTtsOverlayAttachment("talk_start", "zuiba1");
                        ESP_LOGI(kTag, "[TTS_ANIM] event=overlay_attachment role=nvhai_builtin ready=%d",
                                 overlay_ready ? 1 : 0);
                    }
                    spine->useBilinearFilter(true);
                    LogHomeInitStage("spine_reference_sampling_ready");
                    spine->setAnimation(0, "idle", true);
                    LogHomeInitStage("spine_animation_ready");
                    const float reference_offset_y =
                        std::max(0, height - kReferenceSceneHeight) / 2.0f;
                    spine->setPosition(
                        cubicat::Vector2f(
                            width / 2.0f + kSpinePositionOffsetX,
                            reference_offset_y +
                                kSpinePositionOffsetY));
                    // Only rear clothing belongs behind the tabletop. Keep
                    // xiaobir/xiaobil (foreground forearms and hands) uncut.
                    if (meta.role_id == "nvhai_builtin" && width == 320 && height == 320) {
                        constexpr int kTableBackScreenY = 268;
                        const int table_world_y = height - kTableBackScreenY;
                        for (const char* slot : {"shenti", "dabir", "dabil", "yiling"}) {
                            if (!spine->setSlotMinWorldY(slot, table_world_y)) {
                                ESP_LOGW(kTag, "[TABLECLIP] missing rear slot=%s", slot);
                            }
                        }
                        ESP_LOGI(kTag, "[TABLECLIP] rear_clothes screen_y=%d foreground_arms=preserved",
                                 kTableBackScreenY);
                    }
```
