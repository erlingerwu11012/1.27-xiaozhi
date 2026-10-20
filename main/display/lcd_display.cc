#include "home_lcd_stream.h"
#include "esp_lcd_panel_commands.h"
#include "lcd_display.h"

#include "application.h"
#include "assets.h"
#include "audio_codec.h"
#include "boot_animation_player.h"
#include "board.h"
#include "cubicat_home_player.h"
#include "mcp_card_action.h"
#include "reminder_coordinator.h"
#include "spine_assets.h"
#include "wallpaper_assets.h"
#include "home_render_config.h"
#include "home_frame_pipeline.h"
#include "utils/home_render_options.h"
#include "graphic_engine/drawable/font.h"

#include <algorithm>
#include <cstring>
#include <string>

#include <esp_err.h>
#include <esp_heap_caps.h>
#include <esp_log.h>
#include "utils/home_perf.h"
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

namespace {
constexpr const char* kTag = "CubicatDisplay";
constexpr int kRenderPeriodMs = 10;
constexpr int kDmaStripRows = 16;

struct McpDismissContext {
    LcdDisplay* display;
    uint32_t generation;
    std::string instance_id;
    uint32_t revision;
};

const char* CardField(const char* value) {
    return value == nullptr ? "" : value;
}

void LogReminderCard(const char* event, const McpCardData* card,
                     const char* reason) {
    if (card == nullptr) {
        ESP_LOGI(kTag, "[REMINDER_CARD] event=%s reason=%s card=none",
                 event == nullptr ? "unknown" : event,
                 reason == nullptr ? "" : reason);
        return;
    }
    ESP_LOGI(kTag,
             "[REMINDER_CARD] event=%s reason=%s instance=%s rev=%u "
             "priority=%s status=%s privacy=%d queue=%d title=\"%s\" "
             "items=\"%s|%s|%s|%s\" actions=\"%s|%s|%s\"",
             event == nullptr ? "unknown" : event,
             reason == nullptr ? "" : reason,
             CardField(card->instance_id), static_cast<unsigned>(card->revision),
             CardField(card->priority), CardField(card->status),
             card->privacy_mode ? 1 : 0, card->queue_count,
             CardField(card->title), CardField(card->items[0]),
             CardField(card->items[1]), CardField(card->items[2]),
             CardField(card->items[3]), CardField(card->primary_label),
             CardField(card->secondary_label), CardField(card->tertiary_label));
}

void SwapRgb565Bytes(uint16_t* pixels, size_t count) {
    for (size_t index = 0; index < count; ++index) {
        const uint16_t value = pixels[index];
        pixels[index] = static_cast<uint16_t>(
            (value << 8) | (value >> 8));
    }
}
}  // namespace

LcdDisplay::LcdDisplay(esp_lcd_panel_io_handle_t panel_io,
                       esp_lcd_panel_handle_t panel,
                       int width,
                       int height)
    : panel_io_(panel_io), panel_(panel) {
    width_ = width;
    height_ = height;
    ui_mutex_ = xSemaphoreCreateRecursiveMutex();
    if (ui_mutex_ == nullptr) {
        ESP_LOGE(kTag, "Failed to create display mutex");
    }
}

LcdDisplay::~LcdDisplay() {
    StopCubicatHome();
    if (clock_pixels_) heap_caps_free(clock_pixels_);
    DismissMcpCard();
    if (ui_mutex_ != nullptr) {
        vSemaphoreDelete(static_cast<SemaphoreHandle_t>(ui_mutex_));
        ui_mutex_ = nullptr;
    }
}

bool LcdDisplay::Lock(int timeout_ms) {
    if (ui_mutex_ == nullptr) return false;
    const TickType_t timeout = timeout_ms < 0
        ? portMAX_DELAY
        : pdMS_TO_TICKS(timeout_ms);
    return xSemaphoreTakeRecursive(
               static_cast<SemaphoreHandle_t>(ui_mutex_), timeout) == pdTRUE;
}

void LcdDisplay::Unlock() {
    if (ui_mutex_ != nullptr) {
        xSemaphoreGiveRecursive(
            static_cast<SemaphoreHandle_t>(ui_mutex_));
    }
}

void LcdDisplay::NotifyRenderTask() {
    DisplayLockGuard lock(this);
    if (auto handle = static_cast<TaskHandle_t>(render_task_.load()))
        xTaskNotifyGive(handle);
}

void LcdDisplay::RecordDisplayActivity() {
    DisplayLockGuard lock(this);
    standby_policy_.Activity(esp_timer_get_time() / 1000);
}

bool LcdDisplay::WakeFromStandbyClock() {
    DisplayLockGuard lock(this);
    const bool was_clock = requested_mode_.load() == DisplayMode::StandbyClock ||
                           active_mode_.load() == DisplayMode::StandbyClock;
    standby_policy_.Activity(esp_timer_get_time() / 1000);
    requested_mode_.store(DisplayMode::Home);
    if (was_clock) NotifyRenderTask();
    return was_clock;
}

void LcdDisplay::TickStandbyClock(bool eligible, bool allow_entry) {
    DisplayLockGuard lock(this);
    eligible = eligible && startup_revealed_.load() && !stop_render_task_.load() &&
        cubicat_home_player_ && !cubicat_home_player_->HasForegroundUi() &&
        mcp_card_data_ == nullptr && !clock_unavailable_.load();
    // Passive identity verification delays entry, but does not wake an existing clock.
    const bool due = standby_policy_.Tick(esp_timer_get_time() / 1000, eligible && allow_entry);
    if (!eligible) {
        if (requested_mode_.load() != DisplayMode::Home) WakeFromStandbyClock();
        return;
    }
    if (requested_mode_.load() == DisplayMode::StandbyClock || due) {
        const auto text = MakeStandbyClockText(time(nullptr));
        if (requested_mode_.load() != DisplayMode::StandbyClock || !(text == clock_text_)) {
            clock_text_ = text;
            clock_dirty_.store(true);
            requested_mode_.store(DisplayMode::StandbyClock);
            NotifyRenderTask();
        }
    }
}

void LcdDisplay::RenderStandbyClock() {
    if (!clock_pixels_) {
        clock_pixels_ = static_cast<uint16_t*>(heap_caps_malloc(
            static_cast<size_t>(width_) * height_ * sizeof(uint16_t),
            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
        if (!clock_pixels_) {
            clock_unavailable_.store(true);
            ESP_LOGE(kTag, "Standby clock framebuffer allocation failed; keeping Home");
            WakeFromStandbyClock();
            return;
        }
    }
    const bool entering = active_mode_.load() != DisplayMode::StandbyClock;
    if (entering) DrainNativeHomeFrames();
    StandbyClockText text;
    {
        DisplayLockGuard lock(this);
        if (requested_mode_.load() != DisplayMode::StandbyClock) return;
        if (entering) {
            cubicat_home_player_->SetActive(false);
            active_mode_.store(DisplayMode::StandbyClock);
        }
        if (!clock_dirty_.exchange(false) && !entering) return;
        text = clock_text_;
    }
    DrawStandbyClock(clock_pixels_, width_, height_, text);
    if (!text.valid) {
        // Reuse the existing 20px Chinese font; no LVGL or new font allocation.
        const auto& font = DefaultFontData;
        const char* label = "未校时";
        const int stride = 4 + (font.fontSize * font.fontSize + 7) / 8;
        int cursor = (width_ - 3 * font.fontSize) / 2;
        for (int ch = 0; ch < 3; ++ch) {
            const char utf8[] = {label[ch*3], label[ch*3+1], label[ch*3+2], 0};
            const int index = getCharIndex(font.charSet, utf8);
            if (index < 0 || index >= font.charCount) continue;
            const uint8_t* glyph = font.glyphData + index * stride;
            const int w = glyph[2] - glyph[0], h = glyph[3] - glyph[1];
            for (int y = 0; y < h; ++y) for (int x = 0; x < w; ++x) {
                const int bit = y * w + x;
                const int px = cursor + glyph[0] + x;
                const int py = height_ * 216 / 320 + glyph[1] + y;
                if ((glyph[4 + bit/8] & (0x80 >> (bit%8))) &&
                    px >= 0 && px < width_ && py >= 0 && py < height_)
                    clock_pixels_[py*width_ + px] = 0xFFFF;
            }
            cursor += font.fontSize;
        }
    }
    const bool ok = SubmitNativeHomeFrame(clock_pixels_, width_, 0, 0,
                                          width_, height_, true, true);
    if (!ok) {
        // A partial transfer must not leave a dark/stalled clock on the panel.
        clock_unavailable_.store(true);
        ESP_LOGE(kTag, "Standby clock transfer failed; restoring Home");
        WakeFromStandbyClock();
        return;
    }
    DisplayLockGuard lock(this);
    if (entering && requested_mode_.load() == DisplayMode::StandbyClock) {
        if (auto* backlight = Board::GetInstance().GetBacklight())
            backlight->SetTemporaryBrightness(true, kStandbyClockBrightness);
    }
}

bool LcdDisplay::RestoreHomeFromClock() {
    DrainNativeHomeFrames();
    cubicat_home_player_->ResumeAfterStandby();
    cubicat_home_player_->Tick();
    if (!cubicat_home_player_->PresentFullFrame()) return false;
    DisplayLockGuard lock(this);
    active_mode_.store(DisplayMode::Home);
    if (auto* backlight = Board::GetInstance().GetBacklight())
        backlight->SetTemporaryBrightness(false, kStandbyClockBrightness);
    return true;
}

void LcdDisplay::RenderTaskEntry(void *arg) {
    auto *self = static_cast<LcdDisplay *>(arg);
    while (!self->stop_render_task_.load()) {
        const TickType_t started = xTaskGetTickCount();
        if (self->requested_mode_.load() == DisplayMode::StandbyClock) {
            self->RenderStandbyClock();
        } else if (self->active_mode_.load() == DisplayMode::StandbyClock) {
            self->RestoreHomeFromClock();
        } else if (self->cubicat_home_player_ && self->cubicat_home_player_->IsActive()) {
            self->cubicat_home_player_->Tick();
        }
        if (self->stop_render_task_.load()) break;
        const TickType_t elapsed = xTaskGetTickCount() - started;
        const TickType_t period = pdMS_TO_TICKS(kRenderPeriodMs);
        const bool sleeping = self->requested_mode_.load() == DisplayMode::StandbyClock &&
            self->active_mode_.load() == DisplayMode::StandbyClock;
        // Clock updates come from the existing 1Hz application tick only when
        // the formatted minute/date changes. Wake/stop notifications interrupt this wait.
        ulTaskNotifyTake(pdTRUE, sleeping ? portMAX_DELAY :
                         (elapsed >= period ? 1 : period - elapsed));
    }
    {
        DisplayLockGuard lock(self);
        self->render_task_.store(nullptr);
    }
    vTaskDelete(nullptr);
}

bool LcdDisplay::StartRenderTask() {
    if (render_task_.load() != nullptr) return true;
    stop_render_task_.store(false);
    TaskHandle_t handle = nullptr;
    const BaseType_t result = xTaskCreatePinnedToCore(
        RenderTaskEntry,
        "cubicat_home",
        12288,
        this,
        1,
        &handle,
#if CONFIG_SOC_CPU_CORES_NUM > 1
        1
#else
        0
#endif
    );
    if (result != pdPASS) {
        ESP_LOGE(kTag, "Failed to create Cubicat Home task");
        return false;
    }
    render_task_.store(handle);
    return true;
}

void LcdDisplay::SetStartupRevealCallback(std::function<void()> callback) {
    startup_reveal_callback_ = std::move(callback);
    TryRevealStartup();
}

void LcdDisplay::NotifyStartupFrameReady() {
    startup_frame_ready_.store(true);
    TryRevealStartup();
}

void LcdDisplay::ArmStartupReveal() {
    startup_reveal_armed_.store(true);
    TryRevealStartup();
}

void LcdDisplay::TryRevealStartup() {
    if (!startup_frame_ready_.load() ||
        !startup_reveal_armed_.load()) {
        return;
    }
    bool expected = false;
    if (!startup_revealed_.compare_exchange_strong(expected, true)) return;

    if (startup_reveal_callback_) {
        startup_reveal_callback_();
    }
}

bool LcdDisplay::PlayStartupAnimation(std::function<void()> on_started) {
    void* animation_data = nullptr;
    size_t animation_size = 0;
    if (!Assets::GetInstance().GetAssetData(
            "boot.anim", animation_data, animation_size)) {
        ESP_LOGW(kTag,
                 "boot.anim is unavailable; revealing prepared Home frame");
        ArmStartupReveal();
        if (on_started) on_started();
        return false;
    }

    const bool home_was_active =
        cubicat_home_player_ != nullptr &&
        cubicat_home_player_->IsActive();
    if (cubicat_home_player_ != nullptr) {
        cubicat_home_player_->SetActive(false);
    }
    StopRenderTask();
    DrainNativeHomeFrames();

    bool start_notified = false;
    BootAnimationPlayer animation;
    const bool played = animation.Play(
        animation_data,
        animation_size,
        width_,
        height_,
        [this](const uint16_t* pixels,
               int stride,
               int x1,
               int y1,
               int x2,
               int y2) {
            return SubmitNativeHomeFrame(
                pixels, stride, x1, y1, x2, y2);
        },
        [this, &on_started, &start_notified]() {
            start_notified = true;
            ArmStartupReveal();
            if (on_started) on_started();
        });

    if (!start_notified) {
        // Validation/allocation failure happens before the black frame.  The
        // already-prepared Home frame remains the safe fallback.
        ArmStartupReveal();
        if (on_started) on_started();
    }

    if (cubicat_home_player_ != nullptr) {
        if (!cubicat_home_player_->PresentFullFrame()) {
            ESP_LOGE(kTag, "Unable to restore Home after startup animation");
        }
        cubicat_home_player_->SetActive(home_was_active);
        if (home_was_active) StartRenderTask();
    }
    return played;
}

void LcdDisplay::StopRenderTask() {
    stop_render_task_.store(true);
    NotifyRenderTask();
    // Never force-delete a task that may own borrowed packets or a snapshot.
    unsigned waits = 0;
    while (render_task_.load() != nullptr) {
        vTaskDelay(pdMS_TO_TICKS(10));
        if (++waits % 100 == 0)
            ESP_LOGW(kTag, "Waiting for Home rendering to finish before shutdown");
    }
    requested_mode_.store(DisplayMode::Home);
    if (active_mode_.exchange(DisplayMode::Home) == DisplayMode::StandbyClock) {
        if (auto* backlight = Board::GetInstance().GetBacklight())
            backlight->SetTemporaryBrightness(false, kStandbyClockBrightness);
    }
    RecordDisplayActivity();
}

void LcdDisplay::StartCubicatHome() {
    if (cubicat_home_player_ != nullptr) {
        cubicat_home_player_->SetActive(true);
        StartRenderTask();
        return;
    }

    // Spine must be ready before Home's first Initialize() loads the character.
    // NVS is already initialized in main.cc before Board/Display creation.
    auto& spine = SpineAssets::GetInstance();
    if (!spine.ready()) {
        if (!spine.Initialize()) {
            ESP_LOGW("CubicatHome",
                     "[SPINEBOOT] no valid role; starting background-only safe mode");
        }
    }
    if (spine.ready()) {
        ESP_LOGI("CubicatHome",
                 "[SPINEBOOT] role assets ready before home init");
    }

    // A bad or empty online wallpaper must never block the factory room.png.
    WallpaperAssets::GetInstance().Initialize();

    cubicat_home_player_ = std::make_unique<CubicatHomePlayer>();
    const bool started = cubicat_home_player_->Start(
        width_,
        height_,
        [this](const uint16_t* pixels,
               int stride,
               int x1,
               int y1,
               int x2,
               int y2,
               bool synchronous) {
            return SubmitNativeHomeFrame(
                pixels, stride, x1, y1, x2, y2, synchronous, true);
        },
        [this](const char* instance_id,
               uint32_t revision,
               const char* action) {
            const std::string card_instance_id =
                instance_id == nullptr ? "" : instance_id;
            const std::string requested =
                action == nullptr ? "" : action;
            ESP_LOGI(kTag,
                     "[REMINDER_CARD] event=ui_action_received instance=%s "
                     "rev=%u action=%s",
                     card_instance_id.c_str(),
                     static_cast<unsigned>(revision), requested.c_str());
            if (requested == "dismiss") {
                Application::GetInstance().Schedule(
                    [this, card_instance_id, revision]() {
                        if (ReminderCoordinator::GetInstance().
                                OnVisualDismissed(
                                    card_instance_id, revision)) {
                            ESP_LOGI(kTag,
                                     "[REMINDER_CARD] event=ui_dismiss_accepted "
                                     "instance=%s rev=%u",
                                     card_instance_id.c_str(),
                                     static_cast<unsigned>(revision));
                            if (!DismissMcpCard(
                                    card_instance_id, revision)) {
                                ESP_LOGW(
                                    kTag,
                                    "Dismiss target was replaced: %s rev=%u",
                                    card_instance_id.c_str(),
                                    static_cast<unsigned>(revision));
                            }
                        } else {
                            ESP_LOGW(kTag,
                                     "[REMINDER_CARD] event=ui_dismiss_rejected "
                                     "instance=%s rev=%u reason=stale_or_replaced",
                                     card_instance_id.c_str(),
                                     static_cast<unsigned>(revision));
                            ShowNotification(
                                "提醒已更新，请查看当前卡片", 1500);
                        }
                    });
                return;
            }
            if (requested != "primary" &&
                requested != "secondary" &&
                requested != "tertiary") {
                ESP_LOGW(kTag, "Rejected Home action: %s",
                         requested.c_str());
                return;
            }
            const McpCardAction card_action =
                requested == "primary"
                    ? McpCardAction::kPrimary
                    : requested == "secondary"
                        ? McpCardAction::kSecondary
                        : McpCardAction::kTertiary;
            Application::GetInstance().Schedule(
                [this, card_instance_id, revision, card_action, requested]() {
                    const auto result =
                        ExecuteMcpCardAction(
                            card_instance_id, revision, card_action);
                    ESP_LOGI(kTag,
                             "[REMINDER_CARD] event=ui_action_result instance=%s "
                             "rev=%u action=%s handled=%d message=\"%s\"",
                             card_instance_id.c_str(),
                             static_cast<unsigned>(revision), requested.c_str(),
                             result.handled ? 1 : 0, result.message.c_str());
                    if (!result.message.empty()) {
                        ShowNotification(
                            result.message.c_str(), 1500);
                    }
                });
        });
    if (!started) {
        ESP_LOGE(kTag,
                 "Cubicat Home initialization failed; "
                 "no legacy fallback is enabled");
        cubicat_home_player_.reset();
        // Do not leave a failed boot permanently black.  Normal boot reaches
        // this callback only from SubmitNativeHomeFrame() after a full frame.
        NotifyStartupFrameReady();
        return;
    }

    UpdateHomeState(current_home_state_);
    if (!StartRenderTask()) {
        cubicat_home_player_->Stop();
        cubicat_home_player_.reset();
        NotifyStartupFrameReady();
    }
}

void LcdDisplay::StopCubicatHome() {
    StopRenderTask();
    DrainNativeHomeFrames();
    if (cubicat_home_player_ != nullptr) {
        cubicat_home_player_->SetActive(false);
        cubicat_home_player_->Stop();
        cubicat_home_player_.reset();
    }
}

void LcdDisplay::SetStatus(const char* status) {
    ESP_LOGI(kTag, "Status: %s", status == nullptr ? "" : status);
    if (cubicat_home_player_) {
        cubicat_home_player_->SetStatusText(
            status == nullptr ? "" : status);
    }
}

void LcdDisplay::ShowNotification(const std::string& notification,
                                  int duration_ms) {
    ShowNotification(notification.c_str(), duration_ms);
}

void LcdDisplay::ShowNotification(const char* notification,
                                  int duration_ms) {
    if (notification && notification[0]) WakeFromStandbyClock();
    ESP_LOGI(kTag, "Notification: %s",
             notification == nullptr ? "" : notification);
    if (cubicat_home_player_ != nullptr) {
        cubicat_home_player_->ShowNotification(
            notification == nullptr ? "" : notification,
            static_cast<uint32_t>(std::max(0, duration_ms)));
    }
}

void LcdDisplay::UpdateHomeState(HomeState state) {
    if (state != HomeState::kIdle && state != HomeState::kAbsent)
        WakeFromStandbyClock();
    current_home_state_ = state;
    if (cubicat_home_player_ == nullptr) return;

    const char* name = "idle";
    switch (state) {
        case HomeState::kAbsent: name = "absent"; break;
        case HomeState::kIdle: name = "idle"; break;
        case HomeState::kPrewake: name = "prewake"; break;
        case HomeState::kListening: name = "listening"; break;
        case HomeState::kThinking: name = "thinking"; break;
        case HomeState::kSpeaking: name = "speaking"; break;
        case HomeState::kReminder: name = "reminder"; break;
    }
    cubicat_home_player_->SetState(name);
}

void LcdDisplay::SetEmotion(const char* emotion) {
    if (emotion == nullptr) return;
    if (std::strcmp(emotion, "neutral") == 0 ||
        std::strcmp(emotion, "idle") == 0 ||
        std::strcmp(emotion, "microchip_ai") == 0) {
        UpdateHomeState(HomeState::kIdle);
    } else if (std::strcmp(emotion, "prewake") == 0) {
        UpdateHomeState(HomeState::kPrewake);
    } else if (std::strcmp(emotion, "sleepy") == 0) {
        UpdateHomeState(HomeState::kAbsent);
    } else if (std::strcmp(emotion, "awe") == 0) {
        UpdateHomeState(HomeState::kListening);
    } else if (std::strcmp(emotion, "doubt") == 0) {
        UpdateHomeState(HomeState::kThinking);
    } else if (std::strcmp(emotion, "new_message") == 0 ||
               std::strcmp(emotion, "reminder_attention") == 0) {
        UpdateHomeState(HomeState::kReminder);
    } else {
        UpdateHomeState(HomeState::kSpeaking);
    }
}

void LcdDisplay::SetTtsPlaybackActive(bool active) {
    if (active) WakeFromStandbyClock();
    if (cubicat_home_player_) cubicat_home_player_->SetTtsPlaybackActive(active);
    NotifyRenderTask();
}

void LcdDisplay::SetChatMessage(const char* role,
                                const char* content) {
    if (content && content[0]) WakeFromStandbyClock();
    if (cubicat_home_player_ == nullptr) return;
    cubicat_home_player_->SetSubtitle(
        role == nullptr ? "" : role,
        hide_subtitle_ || content == nullptr ? "" : content);
}

void LcdDisplay::SetTheme(Theme* theme) {
    if (theme == nullptr) return;
    WakeFromStandbyClock();
    Display::SetTheme(theme);
    if (cubicat_home_player_ != nullptr) {
        cubicat_home_player_->SetBackground(theme->name().c_str());
    }
}

void LcdDisplay::UpdateStatusBar(bool) {
    if (cubicat_home_player_ == nullptr) return;

    const auto device_state =
        Application::GetInstance().GetDeviceState();

    if (device_state == kDeviceStateWifiConfiguring) {
        cubicat_home_player_->SetNetworkState(
            CubicatHomePlayer::NetworkUiState::kConfiguring);
    } else {
        auto& board = Board::GetInstance();
        const char* icon = board.GetNetworkStateIcon();
        if (icon != nullptr &&
            std::strcmp(icon, "wifi_off") == 0) {
            cubicat_home_player_->SetNetworkState(
                CubicatHomePlayer::NetworkUiState::kDisconnected);
        } else {
            cubicat_home_player_->SetNetworkState(
                CubicatHomePlayer::NetworkUiState::kConnected);
        }
    }

    auto* codec = Board::GetInstance().GetAudioCodec();
    cubicat_home_player_->SetMuted(
        codec != nullptr && codec->output_volume() == 0);
}

void LcdDisplay::SetPowerSaveMode(bool on) {
    if (on) {
        if (cubicat_home_player_)cubicat_home_player_->SetActive(false);
        StopRenderTask();
        DrainNativeHomeFrames();
    }
    const esp_err_t result =
        esp_lcd_panel_disp_on_off(panel_, !on);
    if (result != ESP_OK && result != ESP_ERR_NOT_SUPPORTED) {
        ESP_LOGW(kTag, "Panel power mode failed: %s",
                 esp_err_to_name(result));
    }
    if (!on && cubicat_home_player_) {
        cubicat_home_player_->SetActive(true);
        StartRenderTask();
    }
}

void LcdDisplay::ShowQrCode(const char*) {
    ShowNotification(
        "Connect WiFi: Xiaozhi_Prov_xxxx\n"
        "Open http://192.168.4.1",
        30000);
}

void LcdDisplay::SetHideSubtitle(bool hide) {
    hide_subtitle_ = hide;
    if (hide && cubicat_home_player_ != nullptr) {
        cubicat_home_player_->SetSubtitle("", "");
    }
}

void LcdDisplay::ShowLevelOverlay(const char* type, int value,
                                  uint32_t duration_ms) {
    WakeFromStandbyClock();
    if (cubicat_home_player_ != nullptr) {
        cubicat_home_player_->ShowLevelOverlay(type, value, duration_ms);
    }
}

void LcdDisplay::ShowSpineOtaStatus(const char* title, const char* detail,
                                    int progress) {
    WakeFromStandbyClock();
    if (cubicat_home_player_ != nullptr) {
        cubicat_home_player_->ShowSpineOtaStatus(title, detail, progress);
    }
}

void LcdDisplay::DismissSpineOtaStatus() {
    if (cubicat_home_player_ != nullptr) {
        cubicat_home_player_->DismissSpineOtaStatus();
    }
}

void LcdDisplay::FreeMcpCard(McpCardData* card) {
    if (card == nullptr) return;
    free(card->icon);
    free(card->title);
    free(card->status);
    for (int index = 0; index < 4; ++index) {
        free(card->items[index]);
        free(card->item_keys[index]);
    }
    free(card->action_key);
    free(card->owner_user_id);
    free(card->instance_id);
    free(card->priority);
    free(card->primary_label);
    free(card->secondary_label);
    free(card->tertiary_label);
    delete card;
}

void LcdDisplay::McpDismissTimerCallback(void* arg) {
    auto* context = static_cast<McpDismissContext*>(arg);
    if (context == nullptr || context->display == nullptr) return;
    LcdDisplay* display = context->display;
    DisplayLockGuard lock(display);
    if (display->mcp_card_generation_ == context->generation) {
        ESP_LOGI(kTag,
                 "[REMINDER_CARD] event=auto_dismiss instance=%s rev=%u",
                 context->instance_id.c_str(),
                 static_cast<unsigned>(context->revision));
        if (!display->DismissMcpCard(
                context->instance_id, context->revision)) {
            ESP_LOGW(
                kTag,
                "Auto-dismiss target was replaced: %s rev=%u",
                context->instance_id.c_str(),
                static_cast<unsigned>(context->revision));
        }
    }
}

void LcdDisplay::ShowMcpCard(McpCardData* owned) {
    if (owned == nullptr) return;
    WakeFromStandbyClock();
    DisplayLockGuard lock(this);
    DismissMcpCard();
    ++mcp_card_generation_;
    mcp_card_data_ = owned;
    LogReminderCard("display_show", owned, "coordinator_present");
    if (cubicat_home_player_ != nullptr) {
        cubicat_home_player_->ShowMcpCard(owned);
        UpdateHomeState(HomeState::kReminder);
    }

    if (owned->auto_dismiss_ms <= 0) return;
    esp_timer_create_args_t args = {};
    auto* context = new McpDismissContext{
        this, mcp_card_generation_,
        owned->instance_id == nullptr
            ? "" : owned->instance_id,
        owned->revision};
    args.callback = &LcdDisplay::McpDismissTimerCallback;
    args.arg = context;
    args.dispatch_method = ESP_TIMER_TASK;
    args.name = "mcp_dismiss";
    args.skip_unhandled_events = true;
    if (esp_timer_create(&args, &mcp_dismiss_timer_) == ESP_OK) {
        mcp_dismiss_context_ = context;
        esp_timer_start_once(
            mcp_dismiss_timer_,
            static_cast<uint64_t>(owned->auto_dismiss_ms) * 1000ULL);
    } else {
        delete context;
    }
}

void LcdDisplay::DismissMcpCard() {
    DisplayLockGuard lock(this);
    LogReminderCard("display_dismiss", mcp_card_data_, "display_clear");
    if (mcp_dismiss_timer_ != nullptr) {
        esp_timer_stop(mcp_dismiss_timer_);
        esp_timer_delete(mcp_dismiss_timer_);
        mcp_dismiss_timer_ = nullptr;
    }
    delete static_cast<McpDismissContext*>(mcp_dismiss_context_);
    mcp_dismiss_context_ = nullptr;
    if (cubicat_home_player_ != nullptr &&
        mcp_card_data_ != nullptr) {
        cubicat_home_player_->DismissMcpCard();
    }
    FreeMcpCard(mcp_card_data_);
    mcp_card_data_ = nullptr;
    RecordDisplayActivity();
    if (current_home_state_ == HomeState::kReminder) {
        UpdateHomeState(HomeState::kIdle);
    }
}

bool LcdDisplay::DismissMcpCard(
    const std::string& instance_id, uint32_t revision) {
    DisplayLockGuard lock(this);
    if (mcp_card_data_ == nullptr ||
        mcp_card_data_->instance_id == nullptr ||
        instance_id != mcp_card_data_->instance_id ||
        revision != mcp_card_data_->revision) {
        ESP_LOGW(kTag,
                 "[REMINDER_CARD] event=display_dismiss_rejected "
                 "instance=%s rev=%u reason=identity_mismatch",
                 instance_id.c_str(), static_cast<unsigned>(revision));
        return false;
    }
    DismissMcpCard();
    return true;
}

bool LcdDisplay::HandleTouchGesture(int type, float x, float y) {
    constexpr int kTapGesture = 1;
    if (type != kTapGesture ||
        cubicat_home_player_ == nullptr ||
        !cubicat_home_player_->IsActive()) {
        return false;
    }
    return cubicat_home_player_->HandleTouch(x, y);
}

bool LcdDisplay::GetCurrentMcpCardIdentity(
    std::string& instance_id, uint32_t& revision) const {
    DisplayLockGuard lock(const_cast<LcdDisplay*>(this));
    if (mcp_card_data_ == nullptr ||
        mcp_card_data_->instance_id == nullptr ||
        mcp_card_data_->instance_id[0] == '\0') {
        return false;
    }
    instance_id = mcp_card_data_->instance_id;
    revision = mcp_card_data_->revision;
    return true;
}

SpiLcdDisplay::SpiLcdDisplay(
    esp_lcd_panel_io_handle_t panel_io,
    esp_lcd_panel_handle_t panel,
    int width,
    int height,
    int offset_x,
    int offset_y,
    bool mirror_x,
    bool mirror_y,
    bool swap_xy)
    : LcdDisplay(panel_io, panel, width, height) {
    InitializeHomeRenderConfig();
    native_offset_x_ = offset_x;
    native_offset_y_ = offset_y;
    (void)mirror_x;
    (void)mirror_y;
    (void)swap_xy;

    transfer_done_ = xSemaphoreCreateCounting(2, 2);
    const size_t strip_bytes =
        static_cast<size_t>(width_) * kDmaStripRows * sizeof(uint16_t);
    for (auto& strip : dma_strips_) {
        strip = static_cast<uint16_t*>(heap_caps_malloc(
            strip_bytes,
            MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA | MALLOC_CAP_8BIT));
    }
    if (transfer_done_ == nullptr ||
        dma_strips_[0] == nullptr ||
        dma_strips_[1] == nullptr) {
        ESP_LOGE(kTag, "Failed to allocate native LCD DMA buffers");
        return;
    }

    const esp_lcd_panel_io_callbacks_t callbacks = {
        .on_color_trans_done =
            &SpiLcdDisplay::OnColorTransferDone,
    };
    const esp_err_t callback_result =
        esp_lcd_panel_io_register_event_callbacks(
            panel_io_, &callbacks, this);
    if (callback_result != ESP_OK) {
        ESP_LOGE(kTag, "LCD callback registration failed: %s",
                 esp_err_to_name(callback_result));
        return;
    }

    panel_ready_.store(true);
    stream_enabled_ = cubicat::HomeV2TransmissionRequested();
    cubicat::SetHomeStreamStatus(stream_enabled_, stream_enabled_ ? "enabled" : "disabled_by_mode");
    cubicat::SetHomePixelDiffStatus(false, "disabled_by_mode");
    if (cubicat::HomePipelineRequested()) {
        pipeline_=std::make_unique<HomeFramePipeline>(width_,height_,
            [](void* ctx,const HomeFramePipeline::Frame& f,cubicat::HomeLcdFramePerf& perf) {
                return static_cast<SpiLcdDisplay*>(ctx)->TransferNativeFrame(
                    f.pixels,f.stride,f.x1,f.y1,f.x2,f.y2,perf);
            },this);
        if (!pipeline_->Initialize()) pipeline_.reset();
    } else cubicat::SetHomePipelineStatus(false,"disabled_by_mode");
    const esp_err_t on_result =
        esp_lcd_panel_disp_on_off(panel_, true);
    if (on_result != ESP_OK &&
        on_result != ESP_ERR_NOT_SUPPORTED) {
        ESP_LOGW(kTag, "Unable to turn panel on: %s",
                 esp_err_to_name(on_result));
    }
    ESP_LOGI(kTag,
             "Native ST7796 Cubicat backend ready: %dx%d",
             width_, height_);
    ESP_LOGI(kTag,
             "[DISPLAYOWNER] backend=cubicat panel_callback_owner=SpiLcdDisplay lvgl_panel_driver=0");
}

SpiLcdDisplay::~SpiLcdDisplay() {
    StopCubicatHome();
    pipeline_.reset(); // Stop acknowledgement precedes releasing DMA ownership.
    panel_ready_.store(false);
    if (transfer_done_ && dma_strips_[0] && dma_strips_[1]) {
        while (!WaitForAllTransfers(1000))
            ESP_LOGW(kTag,"Waiting for DMA shutdown; buffers retained");
        ReleaseAllTransferSlots();
    }
    const esp_lcd_panel_io_callbacks_t callbacks{};
    esp_lcd_panel_io_register_event_callbacks(panel_io_,&callbacks,nullptr);
    for (auto& strip : dma_strips_) {
        if (strip != nullptr) {
            heap_caps_free(strip);
            strip = nullptr;
        }
    }
    if (transfer_done_ != nullptr) {
        vSemaphoreDelete(
            static_cast<SemaphoreHandle_t>(transfer_done_));
        transfer_done_ = nullptr;
    }
}

bool SpiLcdDisplay::OnColorTransferDone(
    esp_lcd_panel_io_handle_t,
    esp_lcd_panel_io_event_data_t*,
    void* user_ctx) {
    auto* self = static_cast<SpiLcdDisplay*>(user_ctx);
    if (self == nullptr || self->transfer_done_ == nullptr) {
        return false;
    }
    BaseType_t task_woken = pdFALSE;
    xSemaphoreGiveFromISR(
        static_cast<SemaphoreHandle_t>(self->transfer_done_),
        &task_woken);
    return task_woken == pdTRUE;
}

bool SpiLcdDisplay::TakeTransferSlot(int timeout_ms) {
    if (transfer_done_ == nullptr) return false;
    const TickType_t timeout = timeout_ms < 0
        ? portMAX_DELAY
        : pdMS_TO_TICKS(timeout_ms);
    return xSemaphoreTake(
               static_cast<SemaphoreHandle_t>(transfer_done_),
               timeout) == pdTRUE;
}

bool SpiLcdDisplay::WaitForAllTransfers(int timeout_ms) {
    int acquired = 0;
    for (; acquired < 2; ++acquired) {
        if (!TakeTransferSlot(timeout_ms)) break;
    }
    if (acquired == 2) return true;
    while (acquired-- > 0) {
        xSemaphoreGive(
            static_cast<SemaphoreHandle_t>(transfer_done_));
    }
    return false;
}

void SpiLcdDisplay::ReleaseAllTransferSlots() {
    if (transfer_done_ == nullptr) return;
    xSemaphoreGive(static_cast<SemaphoreHandle_t>(transfer_done_));
    xSemaphoreGive(static_cast<SemaphoreHandle_t>(transfer_done_));
}

bool SpiLcdDisplay::QueueTransfer(
    int x1,
    int y1,
    int x2,
    int y2,
    const uint16_t* pixels) {
    const esp_err_t result = esp_lcd_panel_draw_bitmap(
        panel_, x1, y1, x2, y2, pixels);
    if (result != ESP_OK) {
        ESP_LOGE(kTag, "LCD transfer failed: %s",
                 esp_err_to_name(result));
        return false;
    }
    return true;
}

void SpiLcdDisplay::DrainNativeHomeFrames() {
    if (pipeline_)
        pipeline_->Drain();
}

bool SpiLcdDisplay::SubmitNativeHomeFrame(const uint16_t *pixels, int stride, int x1, int y1,
                                          int x2, int y2, bool synchronous, bool record_perf) {
    if (!panel_ready_.load() || !pixels || stride < width_ || !dma_strips_[0] || !dma_strips_[1])
        return false;
    x1 = std::max(0, x1);
    y1 = std::max(0, y1);
    x2 = std::min(width_, x2);
    y2 = std::min(height_, y2);
    if (x2 <= x1 || y2 <= y1)
        return true;
    // First complete image and boot/restoration frames wait for DMA completion.
    synchronous = synchronous || !startup_frame_ready_.load();
    if (pipeline_)
        return pipeline_->Submit({pixels, stride, x1, y1, x2, y2}, synchronous, record_perf);
    const int64_t start = esp_timer_get_time();
    cubicat::HomeLcdFramePerf perf;
    const bool ok = TransferNativeFrame(pixels, stride, x1, y1, x2, y2, perf);
    if (record_perf) {
        cubicat::RecordHomeLcdAccept(esp_timer_get_time() - start, 0, 0, ok, false);
        cubicat::RecordHomeLcdTransfer(perf);
    }
    return ok;
}

class SpiLcdDisplay::NativeStreamTransport final : public HomeLcdTransport {
public:
    explicit NativeStreamTransport(SpiLcdDisplay &owner) : owner_(owner) {}
    bool Begin(HomePixelRect rect) override {
        // MADCTL already supplies mirror/swap. Apply only the same driver gap.
        const HomeLcdWindowBytes window(rect, owner_.native_offset_x_, owner_.native_offset_y_);
        return esp_lcd_panel_io_tx_param(owner_.panel_io_, LCD_CMD_CASET, window.columns, 4) == ESP_OK &&
               esp_lcd_panel_io_tx_param(owner_.panel_io_, LCD_CMD_RASET, window.rows, 4) == ESP_OK;
    }
    bool TakeSlot() override { return owner_.TakeTransferSlot(1000); }
    void GiveSlot() override { xSemaphoreGive(static_cast<SemaphoreHandle_t>(owner_.transfer_done_)); }
    bool Queue(const uint16_t *data, size_t pixels, bool first) override {
        // Production uses an explicit window + RAMWR for every DMA strip.
        // This matches the panel driver and avoids data-only continuation
        // assumptions across ST7796 module variants and display transitions.
        return esp_lcd_panel_io_tx_color(owner_.panel_io_, HomeLcdStreamCommand(first),
                                        data, pixels * sizeof(uint16_t)) == ESP_OK;
    }
    bool WaitAll() override {
        if (owner_.WaitForAllTransfers(1000)) return true;
        ESP_LOGE(kTag, "LCD stream completion timeout; retaining DMA buffers");
        return false;
    }
    void ReleaseAll() override { owner_.ReleaseAllTransferSlots(); }
private:
    SpiLcdDisplay &owner_;
};

bool SpiLcdDisplay::TransferNativeFrame(const uint16_t *pixels, int stride, int x1, int y1, int x2,
                                        int y2, cubicat::HomeLcdFramePerf &perf) {
    if (stream_enabled_) {
        NativeStreamTransport transport(*this);
        const bool ok = HomeTransferLcdStream(transport, pixels, stride, {x1, y1, x2, y2},
                                              dma_strips_, next_strip_, kDmaStripRows, perf, /*addressed_strips=*/true);
        if (!ok) {
            stream_enabled_ = false; // All DMA work drained before changing backend.
            cubicat::SetHomeStreamStatus(false, "transfer_failed");
            cubicat::RequestHomeLcdRecovery();
            ESP_LOGE(kTag, "[RENDERFALLBACK] LCD strip transfer failed; restore legacy LCD backend");
        } else if (x1 == 0 && y1 == 0 && x2 == width_ && y2 == height_)
            NotifyStartupFrameReady();
        return ok;
    }
    const int64_t start = esp_timer_get_time();
    bool ok = true;
    const int copy_width = x2 - x1;
    for (int strip_y = y1; strip_y < y2; strip_y += kDmaStripRows) {
        const int rows = std::min(kDmaStripRows, y2 - strip_y);
        const int64_t slot_start = esp_timer_get_time();
        const bool ready = TakeTransferSlot(1000);
        perf.wait_us += esp_timer_get_time() - slot_start;
        if (!ready) {
            ++perf.timeouts;
            ok = false;
            ESP_LOGE(kTag, "LCD DMA slot timeout");
            break;
        }
        uint16_t *strip = dma_strips_[next_strip_];
        next_strip_ ^= 1U;
        const int64_t copy_start = esp_timer_get_time();
        for (int row = 0; row < rows; ++row)
            std::memcpy(strip + row * copy_width, pixels + (strip_y + row) * stride + x1,
                        size_t(copy_width) * sizeof(uint16_t));
        perf.copy_us += esp_timer_get_time() - copy_start;
        const int64_t swap_start = esp_timer_get_time();
        SwapRgb565Bytes(strip, size_t(copy_width) * rows);
        perf.swap_us += esp_timer_get_time() - swap_start;
        const int64_t queue_start = esp_timer_get_time();
        const bool queued = QueueTransfer(x1, strip_y, x2, strip_y + rows, strip);
        perf.queue_us += esp_timer_get_time() - queue_start;
        if (!queued) {
            xSemaphoreGive(static_cast<SemaphoreHandle_t>(transfer_done_));
            ok = false;
            break;
        }
    }
    const int64_t completion_start = esp_timer_get_time();
    // A timeout is not permission to reuse a buffer still owned by DMA.
    while (!WaitForAllTransfers(1000)) {
        ++perf.timeouts;
        ok = false;
        ESP_LOGE(kTag, "LCD DMA completion timeout; waiting before buffer reuse");
    }
    perf.wait_us += esp_timer_get_time() - completion_start;
    ReleaseAllTransferSlots();
    perf.transfer_us = esp_timer_get_time() - start;
    perf.pixels = copy_width * (y2 - y1);
    perf.ok = ok;
    if (ok && x1 == 0 && y1 == 0 && x2 == width_ && y2 == height_)
        NotifyStartupFrameReady();
    return ok;
}
