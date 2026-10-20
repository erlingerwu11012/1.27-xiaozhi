/**
 * @file gesture_handler.cc
 * 将手势映射到 Stack-chan 表情、语音、系统功能
 */
#include "gesture_handler.h"
#include "boards/common/board.h"
#include "boards/common/brightness_levels.h"
#include "application.h"
#include "display/display.h"
#include "face_enrollment_manager.h"
#include "assets/lang_config.h"
#include <esp_log.h>
#include <algorithm>
#include <cstdio>
#include <string>
#include <utility>

#include "note_manager.h"
#include "habit_manager.h"
#include "alarm_manager.h"
#include "mcp_card_action.h"
#include "reminder_coordinator.h"

#include <esp_timer.h>

#define TAG "GestureHandler"

namespace touch {

GestureHandler::GestureHandler() = default;

GestureHandler::~GestureHandler() = default;

void GestureHandler::Attach(GestureEngine* engine) {
    engine_ = engine;
    if (engine_) {
        engine_->SetCallback([this](const GestureEvent& e) { OnGesture(e); });
    }
}

void GestureHandler::ScheduleVisual(std::function<void()> fn) {
    Application::GetInstance().Schedule(std::move(fn));
}

static const char* GestureTypeStr(GestureType t) {
    switch (t) {
        case GESTURE_TAP: return "TAP";
        case GESTURE_DOUBLE_TAP: return "DOUBLE_TAP";
        case GESTURE_LONG_PRESS: return "LONG_PRESS";
        case GESTURE_SWIPE_LEFT: return "SWIPE_LEFT";
        case GESTURE_SWIPE_RIGHT: return "SWIPE_RIGHT";
        case GESTURE_SWIPE_UP: return "SWIPE_UP";
        case GESTURE_SWIPE_DOWN: return "SWIPE_DOWN";
        case GESTURE_CIRCLE: return "CIRCLE";
        default: return "?";
    }
}
static const char* ZoneStr(GestureZone z) {
    return z == GESTURE_ZONE_HEAD ? "HEAD" : (z == GESTURE_ZONE_FACE ? "FACE" : "BOTTOM");
}

void GestureHandler::OnGesture(const GestureEvent& e) {
    ESP_LOGD(TAG, "Gesture event: type=%d (%s) zone=%s (%.2f, %.2f)",
             (int)e.type, GestureTypeStr(e.type), ZoneStr(e.zone), e.x, e.y);
    Board* board = board_;
    if (!board) return;

    Display* display = board->GetDisplay();
    AudioCodec* codec = board->GetAudioCodec();
    if (!display) return;

    // The complete first accepted gesture only restores the screen. Do not
    // leak its tap/double-tap/swipe into listening or brightness controls.
    if (display->WakeFromStandbyClock()) return;

    // Every accepted touch is an interaction.  Do this before delegating to a
    // card because card-owned gestures return early from the handler.
    Application::GetInstance().NotifyUserInteraction(true);

    // Enrollment owns DOUBLE_TAP before cards or ordinary touch behavior.
    // This is deliberately global to the existing top touch surface: no new
    // screen or icon is introduced, and all other gestures stay unchanged.
    if (e.type == GESTURE_DOUBLE_TAP &&
        FaceEnrollmentManager::GetInstance().IsActive()) {
        ScheduleVisual([]() {
            FaceEnrollmentManager::GetInstance().Cancel();
        });
        return;
    }

    if (display->HandleTouchGesture(
            static_cast<int>(e.type), e.x, e.y)) {
        return;
    }

    /* 智能管家触摸映射 */
    switch (e.type) {
        case GESTURE_TAP:
            /* 单击：唤醒 AI，进入 Listening。播报期间忽略，避免虚假触摸中断播报。 */
            ScheduleVisual([this, zone = e.zone]() {
                auto& app = Application::GetInstance();
                DeviceState state = app.GetDeviceState();
                if (state == kDeviceStateSpeaking) {
                    int64_t now_ms = esp_timer_get_time() / 1000;
                    if (now_ms - last_tap_ignored_ms_ >= 1000) {
                        last_tap_ignored_ms_ = now_ms;
                        ESP_LOGI(TAG, "[GESTURE] tap_ignored reason=speaking zone=%s", ZoneStr(zone));
                    }
                    return;
                }
                ESP_LOGD(TAG, "touch tap -> StartListening, state=%d", (int)state);
                app.SetListeningReason(kListeningReasonTouch);
                app.StartListening();
            });
            break;

        case GESTURE_LONG_PRESS:
            // The old long-press path entered a fake DND/sleep state and
            // could hide reminders after a noisy touch read.  Keep it inert;
            // CONFIG_TOUCH_DIAGNOSTICS remains available for investigation.
            break;

        case GESTURE_SWIPE_LEFT:
        case GESTURE_SWIPE_RIGHT:
            {
                // 优先检查是否有 MCP 卡片正在显示
                std::string instance_id;
                uint32_t revision = 0;
                ReminderInstance visible;
                if (display->GetCurrentMcpCardIdentity(
                        instance_id, revision) &&
                    ReminderCoordinator::GetInstance().GetById(
                        instance_id, visible) &&
                    visible.revision == revision &&
                    visible.source_type !=
                        ReminderSourceType::kInformation) {
                    McpCardAction action = e.type == GESTURE_SWIPE_LEFT
                        ? McpCardAction::kPrimary
                        : McpCardAction::kSecondary;
                    ScheduleVisual([display, instance_id, revision, action]() {
                        auto result = ExecuteMcpCardAction(
                            instance_id, revision, action);
                        display->ShowNotification(result.message.c_str(), 1500);
                    });
                    break;
                }
                // 无卡片时左右滑暂不处理。
                ESP_LOGD(TAG, "SWIPE_LEFT/RIGHT ignored: no actionable card");
            }
            break;

        case GESTURE_SWIPE_UP:
        case GESTURE_SWIPE_DOWN:
            {
                // Keep the control side anchored to where the finger touched
                // down.  Using the release point makes a diagonal swipe jump
                // between brightness and volume controls.
                bool left_side = e.start_x < 0.5f;
                // Physical gesture direction: up increases, down decreases.
                int delta = (e.type == GESTURE_SWIPE_UP) ? 10 : -10;
                if (left_side) {
                    ScheduleVisual([board, delta]() {
                        auto* backlight = board->GetBacklight();
                        auto* display = board->GetDisplay();
                        if (!backlight || !display) return;

                        int level = BrightnessLevelFromStored(backlight->normal_brightness());
                        level += (delta > 0) ? 1 : -1;
                        level = std::max(1, std::min(kBrightnessLevelCount, level));
                        backlight->SetBrightness(BrightnessPercentForLevel(level), true);
                        display->ShowLevelOverlay("brightness", level, 1500);
                    });
                } else if (codec) {
                    ScheduleVisual([board, delta]() {
                        auto* c = board->GetAudioCodec();
                        auto* display = board->GetDisplay();
                        if (!c || !display) return;
                        int v = c->output_volume() + delta;
                        v = (v < 0) ? 0 : (v > 100 ? 100 : v);
                        c->SetOutputVolume(v);
                        if (v > 0) {
                            display->ShowLevelOverlay("volume", v, 1500);
                        } else {
                            display->ShowLevelOverlay("volume", 0, 1500);
                        }
                        display->UpdateStatusBar(true);
                    });
                } else {
                    ESP_LOGD(TAG, "SWIPE_UP/DOWN skipped: no codec");
                }
            }
            break;

        case GESTURE_DOUBLE_TAP:
            /* 双击：停止当前任务 */
            ScheduleVisual([]() {
                auto& app = Application::GetInstance();
                DeviceState state = app.GetDeviceState();
                if (state == kDeviceStateSpeaking) {
                    app.SetListeningReason(kListeningReasonTouch);
                    app.StartListening();
                } else if (state == kDeviceStateListening) {
                    app.StopListening();
                }
            });
            break;

        case GESTURE_CIRCLE:
            ESP_LOGD(TAG, "CIRCLE ignored");
            break;

        default:
            ESP_LOGD(TAG, "Unhandled gesture type=%d", (int)e.type);
            break;
    }
}

}  // namespace touch
