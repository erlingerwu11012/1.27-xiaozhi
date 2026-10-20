#include "mcp_tools.h"
#include "mcp_server.h"
#include "board.h"
#include "audio/audio_codec.h"
#include "alarm_manager.h"
#include "habit_manager.h"
#include "note_manager.h"
#include "display/display.h"
#include "boards/common/brightness_levels.h"
#include <algorithm>
#include <ctime>
#include <cJSON.h>
#include <esp_log.h>

#define TAG "DeviceTools"

void RegisterDeviceCommonTools(McpServer& server) {
    auto& board = Board::GetInstance();

    // 获取设备状态
    server.AddTool("self.get_device_status",
        "获取设备实时状态（音量、屏幕、时间、今日待办数量等）。调用其他控制工具前若需了解当前状态，先调此工具。",
        PropertyList(),
        [&board](const PropertyList& p) -> ReturnValue {
            // 基础设备状态
            cJSON* root = cJSON_Parse(board.GetDeviceStatusJson().c_str());
            if (!root) root = cJSON_CreateObject();

            // 补充当前时间
            time_t now = time(nullptr);
            if (now > 1000000000L) {
                struct tm t;
                localtime_r(&now, &t);
                char time_buf[64];
                snprintf(time_buf, sizeof(time_buf), "%04d-%02d-%02d %02d:%02d",
                         t.tm_year + 1900, t.tm_mon + 1, t.tm_mday,
                         t.tm_hour, t.tm_min);
                cJSON_AddStringToObject(root, "current_time", time_buf);

                // 今日待办统计
                int cur_min = t.tm_hour * 60 + t.tm_min;
                int alarms_today = 0;
                for (auto& a : AlarmManager::GetInstance().GetAll()) {
                    if (a.enabled && (a.hour * 60 + a.minute) >= cur_min) alarms_today++;
                }
                int habits_today = 0;
                for (auto& h : HabitManager::GetInstance().GetAll()) {
                    if (h.enabled) habits_today++;
                }
                int notes_pending = 0;
                for (auto& n : NoteManager::GetInstance().GetAll()) {
                    if (!n.fired) notes_pending++;
                }
                cJSON_AddNumberToObject(root, "alarms_today", alarms_today);
                cJSON_AddNumberToObject(root, "habits_today", habits_today);
                cJSON_AddNumberToObject(root, "notes_pending", notes_pending);
            } else {
                cJSON_AddStringToObject(root, "current_time", "unknown (no RTC sync yet)");
            }

            char* str = cJSON_PrintUnformatted(root);
            cJSON_Delete(root);
            std::string result(str ? str : "{}");
            free(str);
            return result;
        });

    // 音量调节。这个工具是设备状态控制，不应因语音会话切换而被丢弃。
    auto* set_volume = new McpTool(
        "self.audio_speaker.set_volume",
        "通过语音设置设备扬声器音量。volume 是最终音量，范围 0-100；"
        "用户说调高或调低时，先调用 self.get_device_status 读取当前音量，"
        "再计算目标值调用本工具。",
        PropertyList({Property("volume", kPropertyTypeInteger, 0, 100)}),
        [&board](const PropertyList& p) -> ReturnValue {
            auto* codec = board.GetAudioCodec();
            if (!codec) return McpError{"音频输出设备不可用", "audio_unavailable"};

            const int volume = std::max(0, std::min(100, p["volume"].value<int>()));
            codec->SetOutputVolume(volume);
            ESP_LOGI(TAG, "MCP set volume=%d", volume);

            cJSON* result = cJSON_CreateObject();
            cJSON_AddBoolToObject(result, "ok", true);
            cJSON_AddNumberToObject(result, "volume", volume);
            return result;
        });
    set_volume->set_session_independent(true);
    server.AddTool(set_volume);

    auto display = board.GetDisplay();

    if (display) {
        // 亮度控制。语音和触摸统一使用 1-5 档。
        auto backlight = board.GetBacklight();
        auto* set_brightness = new McpTool(
            "self.screen.set_brightness",
            "设置屏幕亮度档位。brightness 取 1 到 5：1 是最暗，占空比 82%；"
            "5 是最亮，占空比 100%。调亮或调暗时，先调用 self.get_device_status "
            "读取 screen.brightness_level，再对档位加减 1，并限制在 1-5。不要按百分比加减。"
            "兼容旧的 50-100 百分比：50-64 为 1 档，65-74 为 2 档，"
            "75-84 为 3 档，85-94 为 4 档，95-100 为 5 档。6-49 无效。",
            PropertyList({Property("brightness", kPropertyTypeInteger, 1, 100)}),
            [backlight](const PropertyList& p) -> ReturnValue {
                if (!backlight) {
                    return McpError{"屏幕背光设备不可用", "backlight_unavailable"};
                }

                const int level = BrightnessLevelFromToolValue(p["brightness"].value<int>());
                if (level == 0) {
                    return McpError{"亮度必须是 1-5 档，或兼容旧值 50-100；6-49 无效", "invalid_brightness"};
                }
                const uint8_t stored = BrightnessPercentForLevel(level);
                backlight->SetBrightness(stored, true);
                const uint16_t duty = BrightnessDutyCount(stored);
                ESP_LOGI(TAG, "MCP set brightness level=%d duty=%u", level, duty);

                cJSON* result = cJSON_CreateObject();
                cJSON_AddBoolToObject(result, "ok", true);
                cJSON_AddNumberToObject(result, "brightness", level);
                cJSON_AddNumberToObject(result, "brightness_level", level);
                cJSON_AddNumberToObject(result, "duty_percent", duty * 100.0 / 1023.0);
                return result;
            });
        set_brightness->set_session_independent(true);
        server.AddTool(set_brightness);

    }
}

void RegisterDeviceUserTools(McpServer&) {
    // Maintenance MCP endpoints are intentionally unavailable. Internal reboot
    // and renderer configuration remain available to the firmware itself.
}
