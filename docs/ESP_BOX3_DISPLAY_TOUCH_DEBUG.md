# ESP32-S3-BOX-3 屏幕/触摸排查报告

## 一、上电与复位时序（第 3 点）

### 1. LCD 复位电平差异 ⚠️ 建议优先验证

| 板型 | reset_active_high | 当前代码 |
|------|-------------------|----------|
| esp-box（老款） | 0（低电平复位） | esp_box_board.cc |
| esp-box-lite | 0（低电平复位） | esp_box_lite_board.cc |
| **esp-box-3** | **1（高电平复位）** | esp_box3_board.cc L182 |

ILI9341 / ILI9342C 标准为**低电平有效复位**（RST 拉低 = 复位）。  
乐鑫 esp-box 和 esp-box-lite 均使用 `reset_active_high = 0`。  
BOX-3 使用 `reset_active_high = 1`，与其它型号相反。  

**GitHub esp-box#120** 中乐鑫回复：若背光亮但无画面，优先检查 **reset GPIO 电平** 是否正确。

**建议**：在 `esp_box3_board.cc` 中尝试将 `reset_active_high` 从 `1` 改为 `0`。

### 2. 上电延时不足

GitHub issue 中有用户反馈，在 SPI 和显示 init 前增加 **500ms** 延时后显示正常，而当前代码无此延时。

**建议**：在 `esp_lcd_panel_reset(panel)` 之前增加 `vTaskDelay(pdMS_TO_TICKS(500))`。

### 3. 当前 LCD 初始化顺序

```
InitializeIli9341Display():
  esp_lcd_new_panel_io_spi()     // 无延时
  esp_lcd_new_panel_ili9341()
  esp_lcd_panel_reset(panel)     // 立即复位
  esp_lcd_panel_init(panel)
  esp_lcd_panel_disp_on_off(true)
```

复位与 init 之间没有额外延时。

---

## 二、GFX 渲染与显示逻辑（第 4 点）

### 1. 显示链路

```
procedural_emote::Update() → 200x120 RGB565A8 buffer
    ↓
gfx_img_set_src(g_obj_img_face, &g_face_img_dsc)
    ↓
gfx_emote 内部合成
    ↓
EmoteEngine::OnFlush(x_start, y_start, x_end, y_end, color_data)
    ↓
esp_lcd_panel_draw_bitmap(panel, ...)
```

### 2. 可能问题点

- **gfx_emote 任务**：栈 8KB，30 FPS，需确认是否定期调用 OnFlush
- **首帧**：已在 SetupUI 中设置初始 `gfx_img_set_src`，理论上首帧有内容
- **背光**：`DISPLAY_BACKLIGHT_OUTPUT_INVERT = false`，高电平点亮，与官方说明一致

### 3. 建议的调试方法

1. **临时关闭程序化表情**，验证基础显示：
   ```kconfig
   # sdkconfig 或 menuconfig
   CONFIG_USE_PROCEDURAL_STACKCHAN_EMOTE=n
   ```
   若改用 Emoji 动画后仍白屏，问题在 LCD 初始化或 SPI；若有画面，问题在 procedural 或 GFX 合成。

2. **在 OnFlush 中加日志**（`emote_display.cc`）：
   ```cpp
   void EmoteEngine::OnFlush(...) {
       ESP_LOGD(TAG, "OnFlush %d,%d -> %d,%d", x_start, y_start, x_end, y_end);
       // ...
   }
   ```
   确认 flush 是否被调用及调用频率。

3. **提高日志级别**：`idf.py menuconfig` → Component config → Log output → Default log verbosity → Debug，观察是否有 GFX 或 LCD 相关错误。

---

## 三、修改建议优先级

| 优先级 | 修改项 | 位置 | 说明 |
|--------|--------|------|------|
| 1 | reset_active_high: 1 → 0 | esp_box3_board.cc L182 | 与 esp-box / esp-box-lite 统一 |
| 2 | 增加 500ms 上电延时 | esp_lcd_panel_reset 之前 | 参考 GitHub issue |
| 3 | 关闭 procedural 测试 | sdkconfig | 区分 LCD 与 GFX 问题 |
| 4 | OnFlush 调试日志 | emote_display.cc | 验证是否刷新到 LCD |
