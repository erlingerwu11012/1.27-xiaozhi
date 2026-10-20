#include "minute_scheduler.h"
#include <memory>

#include "application.h"
#include "board.h"
#include "display.h"
#include "system_info.h"
#include "audio_codec.h"
#include "mqtt_protocol.h"
#include "websocket_protocol.h"
#include "assets/lang_config.h"
#include "mcp_server.h"
#include "assets.h"
#include "settings.h"
#include "spine_assets.h"
#include "spine_ota.h"
#include "wallpaper_assets.h"
#include "wallpaper_ota.h"
#include "alarm_manager.h"
#include "note_manager.h"
#include "habit_manager.h"
#include "behavior_logger.h"
#include "proactive_manager.h"
#include "user_context.h"
#include "identity_manager.h"
#include "boards/common/esp32_camera.h"
#include "boards/esp-box-3/camera_manager.h"
#include "task_diagnostics.h"
#include "test_observability.h"
#include "reminder_coordinator.h"
#include "reminder_control_client.h"
#include "reminder_voice_service.h"
#include "face_roster.h"
#include "face_enrollment_manager.h"
#include "face_config_store.h"
#include "presence_context.h"
#include "proactive_wake_coordinator.h"
#include "vision_credentials.h"

#include <cstring>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <esp_log.h>
#include <cJSON.h>
#include <driver/gpio.h>
#include <arpa/inet.h>
#define TAG "Application"

namespace {

struct MainWsOpenTaskArgs {
    Application* app = nullptr;
    main_ws_open::WorkerSnapshot snapshot;
};

struct BootSoundTaskArgs {
    AudioService* audio_service = nullptr;
    const char* data = nullptr;
    size_t size = 0;
};

std::mutex g_visual_ota_mutex;
bool g_visual_ota_running = false;
constexpr time_t kReminderInteractionMaxSeconds = 3 * 60;

bool TryAcquireVisualOta() {
    std::lock_guard<std::mutex> lock(g_visual_ota_mutex);
    if (g_visual_ota_running) return false;
    g_visual_ota_running = true;
    return true;
}

void ReleaseVisualOta() {
    std::lock_guard<std::mutex> lock(g_visual_ota_mutex);
    g_visual_ota_running = false;
}

}  // namespace


static const char* const STATE_STRINGS[] = {
    "unknown",
    "starting",
    "configuring",
    "idle",
    "connecting",
    "listening",
    "speaking",
    "upgrading",
    "activating",
    "audio_testing",
    "fatal_error",
    "invalid_state"
};

static const char* DeviceStateName(DeviceState state) {
    const size_t n = sizeof(STATE_STRINGS) / sizeof(STATE_STRINGS[0]);
    const size_t i = static_cast<size_t>(state);
    return i < n ? STATE_STRINGS[i] : "invalid_state";
}

// Upper bound for waiting on the server's `spine_ota_ack` after reporting
// success. On timeout we never re-download; we reboot relying on the persisted
// local completion record and re-send success on the next connection.
constexpr int kSpineOtaAckTimeoutMs = 5000;
constexpr uint32_t kActivationPollIntervalMs = 3000;
constexpr uint32_t kActivationAnnouncementIntervalMs = 120000;
constexpr uint32_t kActivationErrorRetryMinMs = 10000;
constexpr uint32_t kActivationErrorRetryMaxMs = 60000;

Application::Application() {
    event_group_ = xEventGroupCreate();

#if CONFIG_USE_DEVICE_AEC && CONFIG_USE_SERVER_AEC
#error "CONFIG_USE_DEVICE_AEC and CONFIG_USE_SERVER_AEC cannot be enabled at the same time"
#elif CONFIG_USE_DEVICE_AEC
    aec_mode_ = kAecOnDeviceSide;
#elif CONFIG_USE_SERVER_AEC
    aec_mode_ = kAecOnServerSide;
#else
    aec_mode_ = kAecOff;
#endif

    esp_timer_create_args_t clock_timer_args = {
        .callback = [](void* arg) {
            Application* app = (Application*)arg;
            xEventGroupSetBits(app->event_group_, MAIN_EVENT_CLOCK_TICK);
        },
        .arg = this,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "clock_timer",
        .skip_unhandled_events = true
    };
    esp_timer_create(&clock_timer_args, &clock_timer_handle_);

    esp_timer_create_args_t connecting_timer_args = {
        .callback = [](void* arg) {
            Application* app = static_cast<Application*>(arg);
            app->Schedule([app]() { app->OnConnectingTimeout(); });
        },
        .arg = this,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "connecting_to",
        .skip_unhandled_events = true
    };
    esp_timer_create(&connecting_timer_args, &connecting_timer_handle_);
}

Application::~Application() {
    if (clock_timer_handle_ != nullptr) {
        esp_timer_stop(clock_timer_handle_);
        esp_timer_delete(clock_timer_handle_);
    }
    if (connecting_timer_handle_ != nullptr) {
        esp_timer_stop(connecting_timer_handle_);
        esp_timer_delete(connecting_timer_handle_);
        connecting_timer_handle_ = nullptr;
    }
    vEventGroupDelete(event_group_);
}

void Application::CheckAssetsVersion() {
    auto& board = Board::GetInstance();
    auto display = board.GetDisplay();
    auto& assets = Assets::GetInstance();

    if (!assets.partition_valid()) {
        ESP_LOGW(TAG, "Assets partition is disabled for board %s", BOARD_NAME);
        return;
    }
    
    Settings settings("assets", true);
    // Check if there is a new assets need to be downloaded
    std::string download_url = settings.GetString("download_url");

    if (!download_url.empty()) {
        settings.EraseKey("download_url");

        char message[256];
        snprintf(message, sizeof(message), Lang::Strings::FOUND_NEW_ASSETS, download_url.c_str());
        Alert(Lang::Strings::LOADING_ASSETS, message, "cloud_arrow_down", Lang::Sounds::OGG_UPGRADE);
        
        // Wait for the audio service to be idle for 3 seconds
        vTaskDelay(pdMS_TO_TICKS(3000));
        SetDeviceState(kDeviceStateUpgrading);
        board.SetPowerSaveMode(false);
        display->SetChatMessage("system", Lang::Strings::PLEASE_WAIT);

        bool success = assets.Download(download_url, [display](int progress, size_t speed) -> void {
            std::thread([display, progress, speed]() {
                char buffer[32];
                snprintf(buffer, sizeof(buffer), "%d%% %uKB/s", progress, speed / 1024);
                display->SetChatMessage("system", buffer);
            }).detach();
        });

        board.SetPowerSaveMode(true);
        vTaskDelay(pdMS_TO_TICKS(1000));

        if (!success) {
            Alert(Lang::Strings::ERROR, Lang::Strings::DOWNLOAD_ASSETS_FAILED, "sad", Lang::Sounds::OGG_EXCLAMATION);
            vTaskDelay(pdMS_TO_TICKS(2000));
            return;
        }
    }

    // Apply assets
    assets.Apply();
    display->SetChatMessage("system", "");
    display->SetEmotion("microchip_ai");
}

void Application::CheckNewVersion(Ota& ota) {
    // Bootstrap: at most 4 real CheckVersion calls with 2s/4s/8s backoff after failures.
    constexpr int kMaxBootstrapAttempts = 4;
    constexpr int kBackoffAfterFailSec[] = {2, 4, 8};
    auto& board = Board::GetInstance();
    bool network_ok = false;

    for (int index = 1; index <= kMaxBootstrapAttempts; ++index) {
        SetDeviceState(kDeviceStateActivating);
        auto display = board.GetDisplay();
        display->SetStatus(Lang::Strings::CHECKING_NEW_VERSION);

        ESP_LOGI(TAG, "[OTA_BOOT] event=attempt index=%d", index);
        if (!ota.CheckVersion()) {
            const char* reason = ota.GetLastCheckReason();
            ESP_LOGW(TAG, "[OTA_BOOT] event=result index=%d ok=0 reason=%s", index, reason);
            if (index >= kMaxBootstrapAttempts) {
                break;
            }
            int retry_delay = kBackoffAfterFailSec[index - 1];
            char buffer[256];
            snprintf(buffer, sizeof(buffer), Lang::Strings::CHECK_NEW_VERSION_FAILED, retry_delay,
                     ota.GetCheckVersionUrl().c_str());
            Alert(Lang::Strings::ERROR, buffer, "cloud_slash", Lang::Sounds::OGG_EXCLAMATION);
            ESP_LOGW(TAG, "Check new version failed, retry in %d seconds (%d/%d)", retry_delay, index,
                     kMaxBootstrapAttempts);
            // Wait the advertised delay; do not abort on Idle (Alert briefly enters Idle).
            for (int i = 0; i < retry_delay; i++) {
                vTaskDelay(pdMS_TO_TICKS(1000));
            }
            continue;
        }

        ESP_LOGI(TAG, "[OTA_BOOT] event=result index=%d ok=1 websocket_config=%d", index,
                 ota.HasWebsocketConfig() ? 1 : 0);
        network_ok = true;
        break;
    }

    if (!network_ok) {
        if (ota.RestoreValidatedWebsocketSnapshot()) {
            // Use last verified WSS config; skip upgrade/activation for this boot.
            xEventGroupSetBits(event_group_, MAIN_EVENT_CHECK_NEW_VERSION_DONE);
            return;
        }
        // No validated cache: keep retrying forever with clear UX — never fall through to empty MQTT.
        ESP_LOGE(TAG, "[OTA_BOOT] event=bootstrap_exhausted cache=0");
        while (true) {
            Alert(Lang::Strings::ERROR, Lang::Strings::NETWORK_UNAVAILABLE_RETRYING, "cloud_slash",
                  Lang::Sounds::OGG_EXCLAMATION);
            auto display = board.GetDisplay();
            display->SetStatus(Lang::Strings::NETWORK_UNAVAILABLE_RETRYING);
            constexpr int kExtendedRetrySec = 8;
            for (int i = 0; i < kExtendedRetrySec; i++) {
                vTaskDelay(pdMS_TO_TICKS(1000));
                if (device_state_ == kDeviceStateIdle) {
                    break;
                }
            }
            SetDeviceState(kDeviceStateActivating);
            display->SetStatus(Lang::Strings::CHECKING_NEW_VERSION);
            ESP_LOGI(TAG, "[OTA_BOOT] event=attempt index=extended");
            if (ota.CheckVersion()) {
                ESP_LOGI(TAG, "[OTA_BOOT] event=result index=extended ok=1 websocket_config=%d",
                         ota.HasWebsocketConfig() ? 1 : 0);
                network_ok = true;
                break;
            }
            ESP_LOGW(TAG, "[OTA_BOOT] event=result index=extended ok=0 reason=%s",
                     ota.GetLastCheckReason());
        }
    }

    if (ota.HasNewVersion()) {
        if (UpgradeFirmware(ota)) {
            return; // This line will never be reached after reboot
        }
        // If upgrade failed, continue to normal operation (don't break, just fall through)
    }

    // No new version, mark the current version as valid
    ota.MarkCurrentVersionValid();
    if (!ota.HasActivationCode() && !ota.HasActivationChallenge()) {
        xEventGroupSetBits(event_group_, MAIN_EVENT_CHECK_NEW_VERSION_DONE);
        return;
    }

    // An activation record means the user must finish web binding before this
    // device can connect its primary conversation protocol.  This call blocks
    // intentionally; it retains the local code subtitle and keeps all normal
    // WebSocket/dialogue setup below this point unreachable until HTTP 200.
    if (WaitForActivation(ota)) {
        xEventGroupSetBits(event_group_, MAIN_EVENT_CHECK_NEW_VERSION_DONE);
    }
}

bool Application::WaitForActivation(Ota& ota) {
    auto* display = Board::GetInstance().GetDisplay();
    uint32_t error_retry_ms = kActivationErrorRetryMinMs;
    TickType_t next_request_tick = xTaskGetTickCount();
    TickType_t next_announcement_tick = 0;
    std::string displayed_code;

    while (true) {
        if (ota.HasActivationCode() && ota.GetActivationCode() != displayed_code) {
            displayed_code = ota.GetActivationCode();
            ShowActivationCode(displayed_code);
            next_announcement_tick = xTaskGetTickCount() +
                                     pdMS_TO_TICKS(kActivationAnnouncementIntervalMs);
        } else if (!displayed_code.empty() && display != nullptr) {
            // The ordinary subtitle area is deliberately kept reserved for the
            // activation code until the server confirms binding.
            std::string subtitle = std::string("您的激活码是：") + displayed_code;
            display->SetStatus(Lang::Strings::ACTIVATION);
            display->SetChatMessage("system", subtitle.c_str());
        }

        const TickType_t now = xTaskGetTickCount();
        if (!displayed_code.empty() && next_announcement_tick != 0 &&
            static_cast<int32_t>(now - next_announcement_tick) >= 0 &&
            audio_service_.IsPlaybackDrained()) {
            ShowActivationCode(displayed_code);
            next_announcement_tick = xTaskGetTickCount() +
                                     pdMS_TO_TICKS(kActivationAnnouncementIntervalMs);
        }

        if (static_cast<int32_t>(now - next_request_tick) < 0) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        if (!ota.HasActivationCode() || !ota.HasActivationChallenge()) {
            // Refresh a missing/expired challenge or an invalid/missing code
            // without replacing the retained subtitle with a network alert or
            // letting the normal protocol start.
            ESP_LOGW(TAG, "[ACTIVATION] event=metadata_incomplete action=refresh code=%d challenge=%d",
                     ota.HasActivationCode() ? 1 : 0,
                     ota.HasActivationChallenge() ? 1 : 0);
            const bool refreshed = ota.CheckVersion();
            next_request_tick = xTaskGetTickCount() +
                pdMS_TO_TICKS(refreshed ? kActivationPollIntervalMs : error_retry_ms);
            if (!refreshed) {
                error_retry_ms = std::min(error_retry_ms * 2, kActivationErrorRetryMaxMs);
            } else {
                error_retry_ms = kActivationErrorRetryMinMs;
            }
            continue;
        }

        const esp_err_t result = ota.Activate();
        if (result == ESP_OK) {
            if (display != nullptr) {
                display->SetChatMessage("system", "");
            }
            ESP_LOGI(TAG, "[ACTIVATION] event=bound");
            return true;
        }

        if (result == ESP_ERR_TIMEOUT) {
            // HTTP 202: pairing is pending.  Poll quietly at the documented
            // cadence; do not re-speak the code on every response.
            next_request_tick = xTaskGetTickCount() +
                                pdMS_TO_TICKS(kActivationPollIntervalMs);
            error_retry_ms = kActivationErrorRetryMinMs;
            continue;
        }

        // Network/service failure: leave the code visible, keep main WSS
        // closed, and refresh OTA/challenge with a capped quiet backoff.
        ESP_LOGW(TAG, "[ACTIVATION] event=request_failed retry_ms=%u",
                 static_cast<unsigned>(error_retry_ms));
        const bool refreshed = ota.CheckVersion();
        next_request_tick = xTaskGetTickCount() +
            pdMS_TO_TICKS(refreshed ? kActivationPollIntervalMs : error_retry_ms);
        if (!refreshed) {
            error_retry_ms = std::min(error_retry_ms * 2, kActivationErrorRetryMaxMs);
        } else {
            error_retry_ms = kActivationErrorRetryMinMs;
        }
    }
}

void Application::ShowActivationCode(const std::string& code) {
    struct digit_sound {
        char digit;
        const std::string_view& sound;
    };
    static const std::array<digit_sound, 10> digit_sounds{{
        digit_sound{'0', Lang::Sounds::OGG_0},
        digit_sound{'1', Lang::Sounds::OGG_1}, 
        digit_sound{'2', Lang::Sounds::OGG_2},
        digit_sound{'3', Lang::Sounds::OGG_3},
        digit_sound{'4', Lang::Sounds::OGG_4},
        digit_sound{'5', Lang::Sounds::OGG_5},
        digit_sound{'6', Lang::Sounds::OGG_6},
        digit_sound{'7', Lang::Sounds::OGG_7},
        digit_sound{'8', Lang::Sounds::OGG_8},
        digit_sound{'9', Lang::Sounds::OGG_9}
    }};

    const std::string subtitle = std::string("您的激活码是：") + code;
    // This sentence uses substantial SRAM, so callers wait for the local
    // playback queue to drain before the two-minute reminder is emitted.
    Alert(Lang::Strings::ACTIVATION, subtitle.c_str(), "link", Lang::Sounds::OGG_ACTIVATION);

    for (const auto& digit : code) {
        auto it = std::find_if(digit_sounds.begin(), digit_sounds.end(),
            [digit](const digit_sound& ds) { return ds.digit == digit; });
        if (it != digit_sounds.end()) {
            audio_service_.PlaySound(it->sound);
        }
    }
}

void Application::Alert(const char* status, const char* message, const char* emotion, const std::string_view& sound) {
    ESP_LOGW(TAG, "Alert [%s] %s: %s", emotion, status, message);
    auto display = Board::GetInstance().GetDisplay();
    display->SetStatus(status);
    display->SetEmotion(emotion);
    display->SetChatMessage("system", message);
    if (!sound.empty()) {
        audio_service_.PlaySound(sound);
    }
}

void Application::DismissAlert() {
    if (device_state_ == kDeviceStateIdle) {
        auto display = Board::GetInstance().GetDisplay();
        display->SetStatus(Lang::Strings::STANDBY);
        display->SetEmotion("neutral");
        display->SetChatMessage("system", "");
    }
}

void Application::ToggleChatState() {
    Board::GetInstance().GetDisplay()->WakeFromStandbyClock();
    if (FaceEnrollmentManager::GetInstance().IsActive()) {
        ESP_LOGI(TAG, "[FACE_ENROLL] event=chat_toggle_ignored");
        return;
    }
    if (device_state_ == kDeviceStateActivating) {
        ESP_LOGI(TAG, "[ACTIVATION] event=input_ignored source=toggle");
        return;
    } else if (device_state_ == kDeviceStateWifiConfiguring) {
        audio_service_.EnableAudioTesting(true);
        SetDeviceState(kDeviceStateAudioTesting);
        return;
    } else if (device_state_ == kDeviceStateAudioTesting) {
        audio_service_.EnableAudioTesting(false);
        SetDeviceState(kDeviceStateWifiConfiguring);
        return;
    }

    if (!protocol_) {
        ESP_LOGE(TAG, "Protocol not initialized");
        return;
    }

    if (device_state_ == kDeviceStateIdle) {
        Schedule([this]() {
            if (!protocol_->IsAudioChannelOpened()) {
                SetDeviceState(kDeviceStateConnecting);
                MainWsPendingIntent intent;
                intent.has_intent = true;
                intent.action = PendingMainWsAction::kToggleChatListening;
                SubmitMainWsOpenRequest(main_ws_open::Source::kManual,
                                        /*require_presence=*/false, intent);
                return;
            }

            // 进入 Listening
            if (listening_reason_ == kListeningReasonUnknown) {
                listening_reason_ = kListeningReasonSystem;
            }
            SetListeningMode(aec_mode_ == kAecOff ? kListeningModeAutoStop : kListeningModeRealtime);
        });
    } else if (device_state_ == kDeviceStateSpeaking) {
        Schedule([this]() {
            AbortSpeaking(kAbortReasonNone);
            ResumeListeningAfterUserInterrupt(kListeningReasonSystem);
        });
    } else if (device_state_ == kDeviceStateListening) {
        Schedule([this]() {
            protocol_->CloseAudioChannel();
        });
    }
}

void Application::StartListening() {
    Board::GetInstance().GetDisplay()->WakeFromStandbyClock();
    if (FaceEnrollmentManager::GetInstance().IsActive()) {
        ESP_LOGI(TAG, "[FACE_ENROLL] event=start_listening_ignored");
        return;
    }
    if (device_state_ == kDeviceStateActivating) {
        ESP_LOGI(TAG, "[ACTIVATION] event=input_ignored source=start_listening");
        return;
    } else if (device_state_ == kDeviceStateWifiConfiguring) {
        audio_service_.EnableAudioTesting(true);
        SetDeviceState(kDeviceStateAudioTesting);
        return;
    }

    if (!protocol_) {
        ESP_LOGE(TAG, "Protocol not initialized");
        return;
    }
    
    if (device_state_ == kDeviceStateIdle) {
        Schedule([this]() {
            if (!protocol_->IsAudioChannelOpened()) {
                SetDeviceState(kDeviceStateConnecting);
                MainWsPendingIntent intent;
                intent.has_intent = true;
                intent.action = PendingMainWsAction::kStartManualListening;
                SubmitMainWsOpenRequest(main_ws_open::Source::kManual,
                                        /*require_presence=*/false, intent);
                return;
            }

            if (listening_reason_ == kListeningReasonUnknown) {
                listening_reason_ = kListeningReasonSystem;
            }
            SetListeningMode(kListeningModeManualStop);
        });
    } else if (device_state_ == kDeviceStateSpeaking) {
        Schedule([this]() {
            AbortSpeaking(kAbortReasonNone);
            if (listening_reason_ == kListeningReasonUnknown) {
                listening_reason_ = kListeningReasonSystem;
            }
            SetListeningMode(kListeningModeManualStop);
        });
    } else if (device_state_ == kDeviceStateListening) {
        Schedule([this]() { EnsureListeningAudio(); });
    }
}

void Application::StopListening() {
    if (device_state_ == kDeviceStateAudioTesting) {
        audio_service_.EnableAudioTesting(false);
        SetDeviceState(kDeviceStateWifiConfiguring);
        return;
    }

    const std::array<int, 3> valid_states = {
        kDeviceStateListening,
        kDeviceStateSpeaking,
        kDeviceStateIdle,
    };
    // If not valid, do nothing
    if (std::find(valid_states.begin(), valid_states.end(), device_state_) == valid_states.end()) {
        return;
    }

    Schedule([this]() {
        if (device_state_ == kDeviceStateListening) {
            protocol_->SendStopListening();
            SetDeviceState(kDeviceStateIdle);
        }
    });
}

void Application::YieldConversationForFaceEnrollment() {
    Schedule([this]() {
        ESP_LOGI(TAG, "[FACE_ENROLL] event=yield_conversation state=%s",
                 STATE_STRINGS[device_state_]);
        if (device_state_ == kDeviceStateSpeaking) {
            AbortSpeaking(kAbortReasonNone);
        }
        ClearTtsStream(true);
        audio_service_.EnableVoiceProcessing(false);
        audio_service_.ResetUploadQueues();
        if (protocol_ && protocol_->IsAudioChannelOpened() &&
            (device_state_ == kDeviceStateListening ||
             device_state_ == kDeviceStateSpeaking)) {
            protocol_->SendStopListening();
        }
        if (device_state_ == kDeviceStateListening ||
            device_state_ == kDeviceStateSpeaking) {
            SetDeviceState(kDeviceStateIdle);
        }
    });
}

void Application::Start() {
    auto& board = Board::GetInstance();
    SetDeviceState(kDeviceStateStarting);

    /* Setup the display */
    auto display = board.GetDisplay();

    // Apply local assets immediately before network is ready
    {
        auto& assets = Assets::GetInstance();
        if (assets.partition_valid() && assets.checksum_valid()) {
            assets.Apply();
        }
        // Spine preload normally happens in LcdDisplay::StartCubicatHome before Home
        // loads the character. Do not re-Initialize (would Shutdown/Close mmap) if ready.
        auto& spine = SpineAssets::GetInstance();
        if (spine.ready()) {
            ESP_LOGI(TAG, "[SPINEBOOT] already ready at Application start slot=%s role=%s",
                     spine.active_label(), spine.meta().role_id.c_str());
        } else if (!spine.Initialize()) {
            ESP_LOGW(TAG, "[SPINEBOOT] Spine role unavailable; UI continues without character");
        }
    }

    // Keep the home subtitle area clear at boot.  The board identifier is
    // still available in diagnostic logs and protocol metadata.

    /* Setup the audio service */
    auto codec = board.GetAudioCodec();
    audio_service_.Initialize(codec);
    audio_service_.Start();

    AudioServiceCallbacks callbacks;
    callbacks.on_send_queue_available = [this]() {
        xEventGroupSetBits(event_group_, MAIN_EVENT_SEND_AUDIO);
    };
    callbacks.on_wake_word_detected = [this](const std::string& wake_word) {
        ESP_LOGD(TAG, "wake callback received: %s", wake_word.c_str());
        xEventGroupSetBits(event_group_, MAIN_EVENT_WAKE_WORD_DETECTED);
    };
    callbacks.on_vad_change = [this](bool speaking) {
        xEventGroupSetBits(event_group_, MAIN_EVENT_VAD_CHANGE);
    };
    audio_service_.SetCallbacks(callbacks);

    // The LCD has already prepared a complete Home frame with the backlight
    // held off.  Play the local brand animation now that audio output is live;
    // PlaySound runs in its own task because queue back-pressure can otherwise
    // delay the first visual frame of a four-second sound.
    display->PlayStartupAnimation([this]() {
        void* sound_data = nullptr;
        size_t sound_size = 0;
        if (!Assets::GetInstance().GetAssetData(
                "boot.ogg", sound_data, sound_size)) {
            ESP_LOGW(TAG, "boot.ogg is unavailable; startup remains silent");
            return;
        }
        auto* args = new BootSoundTaskArgs{
            .audio_service = &audio_service_,
            .data = static_cast<const char*>(sound_data),
            .size = sound_size,
        };
        const BaseType_t result = xTaskCreate(
            [](void* arg) {
                std::unique_ptr<BootSoundTaskArgs> sound(
                    static_cast<BootSoundTaskArgs*>(arg));
                sound->audio_service->PlaySound(
                    std::string_view(sound->data, sound->size));
                vTaskDelete(nullptr);
            },
            "boot_sound",
            4096,
            args,
            4,
            nullptr);
        if (result != pdPASS) {
            ESP_LOGE(TAG, "Unable to create startup sound task");
            delete args;
        }
    });

    // Start the main event loop above codec/camera utility tasks, but below realtime audio input.
    xTaskCreate([](void* arg) {
        task_diag::LogCurrentTask(TAG, "main_event_loop_start", 6, -1);
        ((Application*)arg)->MainEventLoop();
        vTaskDelete(NULL);
    }, "main_event_loop", 10240, this, 6, &main_event_loop_task_handle_);
    task_diag::LogTaskHandle(TAG, "main_event_loop_created", main_event_loop_task_handle_, 6, -1);
    task_diag::StartPeriodicTaskLogger();
    if (!face_config::Start()) {
        ESP_LOGE(TAG, "[FACE_ENROLL] event=config_store status=failed "
                      "code=resource_exhausted");
    }

    /* Start the clock timer to update the status bar */
    esp_timer_start_periodic(clock_timer_handle_, 1000000);

    /* Wait for the network to be ready */
    board.StartNetwork();

    // Update the status bar immediately to show the network state
    display->UpdateStatusBar(true);

    // Check for new assets version
    CheckAssetsVersion();

    // Check for new firmware version or get the MQTT broker address
    Ota ota;
    CheckNewVersion(ota);

    // Initialize the protocol
    display->SetStatus(Lang::Strings::LOADING_PROTOCOL);

    // Add MCP common tools before initializing the protocol
    auto& mcp_server = McpServer::GetInstance();
    mcp_server.AddCommonTools();
    mcp_server.AddUserOnlyTools();

    if (ota.HasMqttConfig()) {
        protocol_ = std::make_unique<MqttProtocol>();
    } else if (ota.HasWebsocketConfig()) {
        protocol_ = std::make_unique<WebsocketProtocol>();
    } else {
        // Never impersonate an unconfigured MQTT endpoint after OTA failure.
        ESP_LOGE(TAG, "[OTA_BOOT] event=protocol_missing refusing_empty_mqtt");
        Alert(Lang::Strings::ERROR, Lang::Strings::NETWORK_UNAVAILABLE_RETRYING, "cloud_slash",
              Lang::Sounds::OGG_EXCLAMATION);
        while (!ota.HasMqttConfig() && !ota.HasWebsocketConfig()) {
            vTaskDelay(pdMS_TO_TICKS(8000));
            ESP_LOGI(TAG, "[OTA_BOOT] event=attempt index=protocol_guard");
            if (ota.CheckVersion()) {
                ESP_LOGI(TAG, "[OTA_BOOT] event=result index=protocol_guard ok=1 websocket_config=%d",
                         ota.HasWebsocketConfig() ? 1 : 0);
            } else if (ota.RestoreValidatedWebsocketSnapshot()) {
                break;
            } else {
                ESP_LOGW(TAG, "[OTA_BOOT] event=result index=protocol_guard ok=0 reason=%s",
                         ota.GetLastCheckReason());
            }
        }
        if (ota.HasMqttConfig()) {
            protocol_ = std::make_unique<MqttProtocol>();
        } else {
            protocol_ = std::make_unique<WebsocketProtocol>();
        }
    }

    protocol_->OnConnected([this]() {
        DismissAlert();
    });

    protocol_->OnNetworkError([this](const std::string& message) {
        last_error_message_ = message;
        xEventGroupSetBits(event_group_, MAIN_EVENT_ERROR);
    });
    protocol_->OnIncomingAudio([this](std::unique_ptr<AudioStreamPacket> packet) {
        audio_service_.RecordIncomingAudioFrame();
        const uint32_t generation = tts_generation_.load(std::memory_order_acquire);
        // Serialize audio with start/stop and interruption. A direct network
        // enqueue could race AbortSpeaking's decoder reset.
        // Keep the extra main-loop backlog bounded if the sender bursts audio
        // while a control operation is blocking the loop.
        if (pending_tts_audio_.fetch_add(1, std::memory_order_acq_rel) >= MAX_DECODE_PACKETS_IN_QUEUE) {
            pending_tts_audio_.fetch_sub(1, std::memory_order_release);
            ESP_LOGD(TAG, "[TTS_LOCAL] event=audio_drop reason=control_queue_full");
            return;
        }
        auto shared_pkt = std::make_shared<std::unique_ptr<AudioStreamPacket>>(std::move(packet));
        Schedule([this, generation, shared_pkt]() {
            pending_tts_audio_.fetch_sub(1, std::memory_order_release);
            HandleIncomingTtsAudio(generation, std::move(*shared_pkt));
        });
    });
    protocol_->OnAudioChannelOpened([this, codec, &board](uint32_t connection_generation) {
        board.SetPowerSaveMode(false);
        if (!protocol_->session_id().empty()) {
            VisionCredentialStore::GetInstance().ApplyHelloSession(
                connection_generation, protocol_->session_id());
            // Keep CameraManager session mirror for any non-HTTP callers; HTTP
            // explain/identify read the atomic VisionCredentialStore snapshot.
            CameraManager::GetInstance().SetSessionId(protocol_->session_id());
            // FaceRoster::OnAudioSessionOpened is owned exclusively by
            // WebsocketProtocol::ParseServerHello — do not reset roster here.
            ProactiveWakeCoordinator::GetInstance().OnAudioChannelReady(
                protocol_->session_id());
        }
        if (protocol_->server_sample_rate() != codec->output_sample_rate()) {
            ESP_LOGI(TAG, "Server TTS %d Hz, device output %d Hz; resampling applied (common for 16k speech servers)",
                protocol_->server_sample_rate(), codec->output_sample_rate());
        }
        // A durable reminder card can outlive a WebSocket reconnect.  Re-open
        // its server-side interaction guard on this fresh audio channel.
        Schedule([this]() {
            FlushPendingReminderProtocolMessages();
            ActivateReminderInteractionIfReady();
        });
    });
    protocol_->OnAudioChannelClosed([this, &board](uint32_t connection_generation) {
        (void)connection_generation;
        board.SetPowerSaveMode(true);
        Schedule([this]() {
            MarkReminderInteractionTransportClosed();
            ClearTtsStream(true);
            // Drop audio still queued for upload: the link is gone and it must
            // not be replayed over the next (fresh) connection.
            audio_service_.ResetUploadQueues();
            audio_service_.ResetDecoder();
            ProactiveWakeCoordinator::GetInstance().OnAudioChannelClosed();
            SetDeviceState(kDeviceStateIdle);
            // A server-side channel close must not discard the local card.
            // While the person remains present, ask the normal WS arbiter for
            // a fresh channel so the card-action listen can resume.
            ActivateReminderInteractionIfReady();
        });
    });
    protocol_->OnIncomingJson([this, display](const cJSON* root,
                                              uint32_t connection_generation) {
        // Parse JSON data
        auto type = cJSON_GetObjectItem(root, "type");
        if (!type || !cJSON_IsString(type)) {
            ESP_LOGW(TAG, "OnIncomingJson: missing or invalid type");
            return;
        }
        if (strcmp(type->valuestring, "tts") == 0) {
            auto state = cJSON_GetObjectItem(root, "state");
            if (!state || !cJSON_IsString(state)) {
                ESP_LOGW(TAG, "OnIncomingJson: tts message missing or invalid state");
                return;
            }
            const auto* request = cJSON_GetObjectItem(root, "request_id");
            const auto* epoch = cJSON_GetObjectItem(root, "abort_epoch");
            std::string owner = cJSON_IsString(request) ? request->valuestring : "";
            if (!owner.empty() && cJSON_IsNumber(epoch)) owner += ":" + std::to_string(epoch->valueint);
            if (strcmp(state->valuestring, "start") == 0) {
                if (FaceEnrollmentManager::GetInstance().IsActive()) {
                    ESP_LOGI(TAG, "[TTS_LOCAL] event=start_drop reason=face_enrollment");
                    return;
                }
                if (!tts_request_gate_.Start(owner)) {
                    ESP_LOGI(TAG, "[TTS_LOCAL] event=start_drop reason=duplicate_or_retired_owner");
                    return;
                }
                // Allocate at receipt, before queuing: following audio/stop
                // must keep this generation even if the main loop is busy.
                const uint32_t generation =
                    tts_generation_.fetch_add(1, std::memory_order_acq_rel) + 1;
                Schedule([this, generation]() {
                    BeginTtsStream(generation);
                });
            } else if (strcmp(state->valuestring, "stop") == 0) {
                if (!tts_request_gate_.Matches(owner)) return;
                const uint32_t generation =
                    tts_generation_.load(std::memory_order_acquire);
                Schedule([this, generation]() {
                    HandleTtsStop(generation);
                });
            } else if (strcmp(state->valuestring, "sentence_start") == 0) {
                if (!tts_request_gate_.Matches(owner)) return;
                auto text = cJSON_GetObjectItem(root, "text");
                if (cJSON_IsString(text)) {
                    ESP_LOGI(TAG, "<< %s", text->valuestring);
                    const uint32_t generation =
                        tts_generation_.load(std::memory_order_acquire);
                    Schedule([this, generation,
                              message = std::string(text->valuestring)]() {
                        QueueTtsSubtitle(generation, audio_service_.NextPlaybackSequence(), message);
                    });
                }
            }
        } else if (strcmp(type->valuestring, "stt") == 0) {
            auto text = cJSON_GetObjectItem(root, "text");
            if (cJSON_IsString(text)) {
                // Keep recognition available for diagnostics; conversation
                // subtitles are reserved for assistant replies.
                ESP_LOGI(TAG, ">> %s", text->valuestring);
            }
        } else if (strcmp(type->valuestring, "llm") == 0) {
            awaiting_server_reply_ = false;
            auto emotion = cJSON_GetObjectItem(root, "emotion");
            if (cJSON_IsString(emotion)) {
                Schedule([this, display, emotion_str = std::string(emotion->valuestring)]() {
                    last_llm_emotion_ = emotion_str;
                    display->SetEmotion(emotion_str.c_str());
                });
            }
        } else if (strcmp(type->valuestring, "identity_context") == 0) {
            // Identity facts are deliberately separate.  A camera-recognised
            // in-room user is never overwritten by the current voiceprint
            // speaker, and neither is rendered on the screen.
            auto* speaker = cJSON_GetObjectItem(root, "current_speaker_user");
            auto* speaker_name = cJSON_GetObjectItem(root, "speaker_display_name");
            if (cJSON_IsString(speaker) && speaker->valuestring && speaker->valuestring[0]) {
                const std::string user_id = speaker->valuestring;
                const std::string name = cJSON_IsString(speaker_name) &&
                        speaker_name->valuestring ? speaker_name->valuestring : "";
                Schedule([user_id, name]() {
                    UserContext::GetInstance().SetCurrentSpeakerUser(user_id, name);
                });
            } else {
                Schedule([]() { UserContext::GetInstance().ClearCurrentSpeakerUser(); });
            }
        } else if (strcmp(type->valuestring, "mcp") == 0) {
            // Do NOT parse MCP on the websocket task: it only has ~6KB and
            // shares it with TLS. initialize (vision/face/reminder capabilities)
            // + ReplyResult is heavy enough to panic (reset_reason=4) right
            // after first wake. Serialize the payload and defer the whole
            // parse to main_event_loop, carrying the source generation captured
            // at RX time — never re-reading the "current" generation later.
            auto payload = cJSON_GetObjectItem(root, "payload");
            if (cJSON_IsObject(payload)) {
                char* printed = cJSON_PrintUnformatted(payload);
                if (printed != nullptr) {
                    std::string message(printed);
                    cJSON_free(printed);
                    const uint32_t source_generation = connection_generation;
                    Schedule([message = std::move(message), source_generation]() {
                        McpServer::GetInstance().ParseMessage(message,
                                                              source_generation);
                    });
                }
            }
        } else if (strcmp(type->valuestring, "display_hint") == 0) {
            auto payload = cJSON_GetObjectItem(root, "payload");
            if (cJSON_IsObject(payload)) {
                auto title = cJSON_GetObjectItem(payload, "title");
                auto* arr = cJSON_GetObjectItem(payload, "items");
                auto* dm = cJSON_GetObjectItem(payload, "auto_dismiss_ms");
                auto* icon = cJSON_GetObjectItem(payload, "icon");
                auto* status = cJSON_GetObjectItem(payload, "status");
                auto* priority = cJSON_GetObjectItem(payload, "priority");
                auto* owner = cJSON_GetObjectItem(payload, "owner_user_id");
                bool valid = cJSON_IsString(title) && title->valuestring &&
                             strlen(title->valuestring) <= 96 &&
                             (!arr || cJSON_IsArray(arr)) &&
                             (!icon || (cJSON_IsString(icon) &&
                                       icon->valuestring &&
                                       strlen(icon->valuestring) <= 8)) &&
                             (!priority ||
                              (cJSON_IsString(priority) &&
                               priority->valuestring &&
                               strcmp(priority->valuestring, "low") == 0)) &&
                             (!owner ||
                              (cJSON_IsString(owner) &&
                               owner->valuestring &&
                               strcmp(owner->valuestring, "default") == 0));
                if (valid && status) {
                    valid = cJSON_IsString(status) &&
                            status->valuestring &&
                            (strcmp(status->valuestring, "ok") == 0 ||
                             strcmp(status->valuestring, "error") == 0 ||
                             strcmp(status->valuestring, "loading") == 0 ||
                             strcmp(status->valuestring, "information") == 0);
                }
                std::vector<std::string> details;
                if (valid && arr) {
                    const int count = cJSON_GetArraySize(arr);
                    valid = count >= 0 && count <= 4;
                    for (int i = 0; valid && i < count; ++i) {
                        cJSON* item = cJSON_GetArrayItem(arr, i);
                        valid = cJSON_IsString(item) && item->valuestring &&
                                strlen(item->valuestring) <= 128;
                        if (valid) details.emplace_back(item->valuestring);
                    }
                }
                // Information/result cards obey the same 30-second no-input
                // rule as a conversation and a reminder card.  Older
                // services may still send an 8-15s hint, but it must not
                // create another device-side idle window.
                int dismiss_ms = LISTENING_TIMEOUT_MS;
                if (dm) {
                    valid = valid && cJSON_IsNumber(dm) &&
                            std::floor(dm->valuedouble) == dm->valuedouble;
                }
                if (valid) {
                    Schedule([title_text = std::string(title->valuestring),
                              details = std::move(details), dismiss_ms]() {
                        ReminderCoordinator::GetInstance().EnqueueInformation(
                            title_text, details,
                            static_cast<uint32_t>(dismiss_ms));
                    });
                } else {
                    Schedule([display]() {
                        display->ShowNotification(
                            "信息卡格式无效", 2000);
                    });
                }
            }
        } else if (strcmp(type->valuestring,
                          "reminder_voice_asset") == 0) {
            ReminderVoiceService::GetInstance().HandleIncomingAssetMessage(
                root);
        } else if (strcmp(type->valuestring,
                          "reminder_voice_error") == 0) {
            ReminderVoiceService::GetInstance().HandleIncomingErrorMessage(
                root);
            ReminderControlClient::GetInstance().Cancel("voice_error");
        } else if (strcmp(type->valuestring, "spine_ota_ack") == 0 ||
                   strcmp(type->valuestring, "wallpaper_ota_ack") == 0) {
            // Server confirmation for a completed visual-resource OTA. The
            // shared visual update gate guarantees there is only one waiter.
            OnSpineOtaAck(root);
        } else if (strcmp(type->valuestring, "system") == 0) {
            auto command = cJSON_GetObjectItem(root, "command");
            if (cJSON_IsString(command)) {
                ESP_LOGI(TAG, "System command: %s", command->valuestring);
                if (strcmp(command->valuestring, "reboot") == 0) {
                    // Do a reboot if user requests a OTA update
                    Schedule([this]() {
                        Reboot();
                    });
                } else if (strcmp(command->valuestring, "update_assets") == 0) {
                    // assets now contains fixed factory fonts, UI, room.png and
                    // the fallback Spine role. It is intentionally not OTA-writable.
                    ESP_LOGW(TAG, "update_assets ignored: fixed factory assets are not OTA-writable");
                } else if (strcmp(command->valuestring, "update_spine") == 0) {
                    // Deep-copy JSON and run on a worker task (do not block MainEventLoop).
                    auto send_failed = [this](const cJSON* task_json, const char* error) {
                        if (!protocol_) return;
                        cJSON* tid = cJSON_GetObjectItem(task_json, "task_id");
                        cJSON* pid = cJSON_GetObjectItem(task_json, "pack_id");
                        if (!cJSON_IsString(tid)) return;
                        cJSON* msg = cJSON_CreateObject();
                        cJSON_AddStringToObject(msg, "type", "spine_ota_status");
                        cJSON_AddStringToObject(msg, "task_id", tid->valuestring);
                        cJSON_AddStringToObject(msg, "pack_id",
                                                cJSON_IsString(pid) ? pid->valuestring : "");
                        cJSON_AddStringToObject(msg, "phase", "failed");
                        cJSON_AddNumberToObject(msg, "progress", 0);
                        cJSON_AddStringToObject(msg, "error", error);
                        cJSON_AddStringToObject(msg, "reason", strcmp(error, "E_BUSY") == 0 ? "worker_creation_failed" : "invalid_bundle");
                        cJSON_AddBoolToObject(msg, "not_accepted", true);
                        char* text = cJSON_PrintUnformatted(msg);
                        if (text) {
                            const bool ok = protocol_->SendText(text);
                            ESP_LOGI(TAG, "[SpineOta] send_status task=%s phase=failed err=%s sent=%d",
                                     tid->valuestring, error, ok ? 1 : 0);
                            cJSON_free(text);
                        }
                        cJSON_Delete(msg);
                    };

                    char* copy = cJSON_PrintUnformatted(root);
                    if (copy == nullptr) {
                        ESP_LOGW(TAG, "update_spine: failed to copy JSON");
                        send_failed(root, "E_BUNDLE");
                    } else {
                        auto* payload = new std::string(copy);
                        cJSON_free(copy);
                        TaskHandle_t handle = nullptr;
                        BaseType_t created = xTaskCreate([](void* arg) {
                            auto* payload = static_cast<std::string*>(arg);
                            cJSON* task_root = cJSON_Parse(payload->c_str());
                            delete payload;
                            if (task_root == nullptr) {
                                ESP_LOGW(TAG, "update_spine: parse copy failed");
                                vTaskDelete(nullptr);
                                return;
                            }
                            ESP_LOGI(TAG, "[SpineOta] phase=received");
                            Application::GetInstance().HandleUpdateSpine(task_root);
                            cJSON_Delete(task_root);
                            vTaskDelete(nullptr);
                        }, "spine_ota", 8192, payload, 5, &handle);
                        if (created != pdPASS) {
                            ESP_LOGE(TAG, "update_spine: xTaskCreate failed (%d)", (int)created);
                            delete payload;
                            send_failed(root, "E_BUSY");
                        } else {
                            task_diag::LogTaskHandle(TAG, "spine_ota_created", handle, 5, -1);
                        }
                    }
                } else if (strcmp(command->valuestring, "update_wallpaper") == 0) {
                    // Wallpaper OTA is independent from role OTA, but the two
                    // visual flash writers are serialized by the shared gate.
                    auto send_failed = [this](const cJSON* task_json, const char* error) {
                        if (!protocol_) return;
                        cJSON* tid = cJSON_GetObjectItem(task_json, "task_id");
                        cJSON* pid = cJSON_GetObjectItem(task_json, "pack_id");
                        if (!cJSON_IsString(tid)) return;
                        cJSON* msg = cJSON_CreateObject();
                        cJSON_AddStringToObject(msg, "type", "wallpaper_ota_status");
                        cJSON_AddStringToObject(msg, "task_id", tid->valuestring);
                        cJSON_AddStringToObject(msg, "pack_id",
                                                cJSON_IsString(pid) ? pid->valuestring : "");
                        cJSON_AddStringToObject(msg, "phase", "failed");
                        cJSON_AddNumberToObject(msg, "progress", 0);
                        cJSON_AddStringToObject(msg, "error", error);
                        char* text = cJSON_PrintUnformatted(msg);
                        if (text) {
                            protocol_->SendText(text);
                            cJSON_free(text);
                        }
                        cJSON_Delete(msg);
                    };
                    char* copy = cJSON_PrintUnformatted(root);
                    if (copy == nullptr) {
                        send_failed(root, "E_BUNDLE");
                    } else {
                        auto* payload = new std::string(copy);
                        cJSON_free(copy);
                        TaskHandle_t handle = nullptr;
                        const BaseType_t created = xTaskCreate([](void* arg) {
                            auto* payload = static_cast<std::string*>(arg);
                            cJSON* task_root = cJSON_Parse(payload->c_str());
                            delete payload;
                            if (task_root != nullptr) {
                                Application::GetInstance().HandleUpdateWallpaper(task_root);
                                cJSON_Delete(task_root);
                            }
                            vTaskDelete(nullptr);
                        }, "wallpaper_ota", 8192, payload, 5, &handle);
                        if (created != pdPASS) {
                            delete payload;
                            send_failed(root, "E_BUSY");
                        } else {
                            task_diag::LogTaskHandle(TAG, "wallpaper_ota_created", handle, 5, -1);
                        }
                    }
                } else {
                    ESP_LOGW(TAG, "Unknown system command: %s", command->valuestring);
                }
            }
        } else if (strcmp(type->valuestring, "alert") == 0) {
            auto status = cJSON_GetObjectItem(root, "status");
            auto message = cJSON_GetObjectItem(root, "message");
            auto emotion = cJSON_GetObjectItem(root, "emotion");
            if (cJSON_IsString(status) && cJSON_IsString(message) && cJSON_IsString(emotion)) {
                Alert(status->valuestring, message->valuestring, emotion->valuestring, Lang::Sounds::OGG_VIBRATION);
            } else {
                ESP_LOGW(TAG, "Alert command requires status, message and emotion");
            }
        } else if (strcmp(type->valuestring, "error") == 0) {
            // ASR/婢堆勀侀崹瀣搼閺堝秴濮熷鍌氱埗閿涘牆顩?code 40000004閿涘绱板鍝勫煑濞撳懘娅庣€电鐦芥稉濠佺瑓閺傚洤鑻熼崶鐐插煂 Idle
            auto code = cJSON_GetObjectItem(root, "code");
            auto message = cJSON_GetObjectItem(root, "message");
            const char* err_msg = (message && cJSON_IsString(message)) ? message->valuestring : Lang::Strings::SERVER_ERROR;
            int code_val = (code && cJSON_IsNumber(code)) ? code->valueint : 0;
            ESP_LOGW(TAG, "Server error type=error code=%d message=%s", code_val, err_msg);
            Schedule([this, err_str = std::string(err_msg)]() {
                if (protocol_ && protocol_->IsAudioChannelOpened()) {
                    protocol_->CloseAudioChannel();
                }
                SetDeviceState(kDeviceStateIdle);
                Alert(Lang::Strings::ERROR, err_str.c_str(), "sad", Lang::Sounds::OGG_EXCLAMATION);
            });
#if CONFIG_RECEIVE_CUSTOM_MESSAGE
        } else if (strcmp(type->valuestring, "custom") == 0) {
            auto payload = cJSON_GetObjectItem(root, "payload");
            ESP_LOGI(TAG, "Received custom message: %s", cJSON_PrintUnformatted(root));
            if (cJSON_IsObject(payload)) {
                Schedule([this, display, payload_str = std::string(cJSON_PrintUnformatted(payload))]() {
                    display->SetChatMessage("system", payload_str.c_str());
                });
            } else {
                ESP_LOGW(TAG, "Invalid custom message format: missing payload");
            }
#endif
        } else if (strcmp(type->valuestring, "pong") == 0) {
            // Application-level Keep-Alive heartbeat reply; ignore silently
            return;
        } else if (strcmp(type->valuestring, "listen") == 0) {
            /* 娴滄垹顏幒銉ь吀閺傤厼褰為敍姘暪閸掔増婀囬崝锛勵伂 stop/detect 鐞涖劎銇氱拠鍡楀焼鐎瑰本鍨氶妴浣筋嚉闂傤參瀹?*/
            auto state = cJSON_GetObjectItem(root, "state");
            if (state && cJSON_IsString(state)) {
                const char* st = state->valuestring;
                if (strcmp(st, "stop") == 0 || strcmp(st, "detect") == 0) {
                    std::string state_str(st);
                    Schedule([this, state_str]() {
                        if (IsReminderInteractionActive()) {
                            ESP_LOGI(TAG,
                                     "[REMINDER_INTERACTION] "
                                     "event=server_listen_ignored state=%s",
                                     state_str.c_str());
                            return;
                        }
                        if (device_state_ == kDeviceStateListening) {
                            audio_service_.EnableVoiceProcessing(false);
                            SetDeviceState(kDeviceStateIdle);
                            ESP_LOGI(TAG, "Listen stopped by server (state=%s)", state_str.c_str());
                        }
                    });
                    return;
                }
            }
        } else {
            ESP_LOGW(TAG, "Unknown message type: %s", type->valuestring);
        }
    });
    bool protocol_started = protocol_->Start();

    SystemInfo::PrintHeapStats();
    SetDeviceState(kDeviceStateIdle);

    has_server_time_ = ota.HasServerTime();
    if (protocol_started) {
        display->SetChatMessage("system", "");
        audio_service_.PlaySound(Lang::Sounds::OGG_SUCCESS);
    }
}

// Add a async task to MainLoop
void Application::Schedule(std::function<void()> callback) {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        main_tasks_.push_back(std::move(callback));
    }
    xEventGroupSetBits(event_group_, MAIN_EVENT_SCHEDULE);
}

// The Main Event Loop controls the chat state and websocket connection
// If other tasks need to access the websocket or chat state,
// they should use Schedule to call this function
void Application::MainEventLoop() {
    while (true) {
        auto bits = xEventGroupWaitBits(event_group_, MAIN_EVENT_SCHEDULE |
            MAIN_EVENT_SEND_AUDIO |
            MAIN_EVENT_WAKE_WORD_DETECTED |
            MAIN_EVENT_VAD_CHANGE |
            MAIN_EVENT_CLOCK_TICK |
            MAIN_EVENT_ERROR, pdTRUE, pdFALSE, portMAX_DELAY);

        if (bits & MAIN_EVENT_ERROR) {
            Schedule([this]() {
                if (protocol_ && protocol_->IsAudioChannelOpened()) {
                    protocol_->CloseAudioChannel();
                }
                SetDeviceState(kDeviceStateIdle);
                Alert(Lang::Strings::ERROR, last_error_message_.c_str(), "sad", Lang::Sounds::OGG_EXCLAMATION);
            });
        }

        // Fair scheduling: handle clock/control before draining audio so the
        // 20s application ping cannot be starved by a full send queue.
        if (bits & MAIN_EVENT_SCHEDULE) {
            std::unique_lock<std::mutex> lock(mutex_);
            auto tasks = std::move(main_tasks_);
            lock.unlock();
            for (auto& task : tasks) {
                task();
            }
        }

        if (bits & MAIN_EVENT_WAKE_WORD_DETECTED) {
            OnWakeWordDetected();
        }

        if (bits & MAIN_EVENT_VAD_CHANGE) {
            if (device_state_ == kDeviceStateListening) {
                auto led = Board::GetInstance().GetLed();
                led->OnStateChanged();
            }
        }

        if (bits & MAIN_EVENT_SEND_AUDIO) {
            static int send_count = 0;
            // Cap packets per turn (~480ms of 60ms frames) then yield so
            // CLOCK_TICK / ping / MCP can run. Re-arm if more remain.
            constexpr int kMaxAudioSendsPerTurn = 8;
            int sent_this_turn = 0;
            while (sent_this_turn < kMaxAudioSendsPerTurn) {
                auto packet = audio_service_.PopPacketFromSendQueue();
                if (!packet) break;
                if (!protocol_) {
                    audio_service_.RecordUploadSendResult(false);
                    break;
                }
                // Local speech remains activity even if this packet cannot be
                // uploaded during congestion. Do not expire listening mid-speech.
                if (device_state_ == kDeviceStateListening && audio_service_.IsVoiceDetected()) {
                    ResetListeningTimeout(false);
                }
                const bool sent = protocol_->SendAudio(std::move(packet));
                audio_service_.RecordUploadSendResult(sent);
                if (!sent) {
                    break;
                }
                ++sent_this_turn;
                if (device_state_ == kDeviceStateListening) {
                    if (++send_count % 100 == 1) {
                        ESP_LOGD(TAG, "[AudioPipe] SendAudio #%d (uploading to server)", send_count);
                    }
                }
            }
            size_t encode_queue = 0, send_queue = 0;
            audio_service_.GetQueueStats(encode_queue, send_queue);
            if (send_queue > 0) {
                xEventGroupSetBits(event_group_, MAIN_EVENT_SEND_AUDIO);
            }
            const bool encode_pressured = encode_queue * 4 >= MAX_ENCODE_TASKS_IN_QUEUE * 3;
            const bool send_pressured = send_queue * 4 >= MAX_SEND_PACKETS_IN_QUEUE * 3;
            if (encode_pressured || send_pressured) {
                static TickType_t last_ws_audio_queue_log_tick = 0;
                TickType_t now = xTaskGetTickCount();
                if ((TickType_t)(now - last_ws_audio_queue_log_tick) >= pdMS_TO_TICKS(1000)) {
                    last_ws_audio_queue_log_tick = now;
                    ESP_LOGW(TAG, "[WS_AUDIO] encode_queue=%u send_queue=%u device_state=%d",
                             (unsigned)encode_queue, (unsigned)send_queue, (int)device_state_);
                }
            }
        }

        if (bits & MAIN_EVENT_CLOCK_TICK) {
            clock_ticks_++;
            auto display = Board::GetInstance().GetDisplay();
            
            const bool face_enrollment_active =
                FaceEnrollmentManager::GetInstance().IsActive();
            if (face_enrollment_active) {
                face_enrollment_was_active_ = true;
            } else if (face_enrollment_was_active_) {
                // Capture/upload do not count as repeated interactions.  The
                // finished result is simply granted one fresh 30s foreground
                // window.
                face_enrollment_was_active_ = false;
                NotifyUserInteraction(false);
            }

            // The single idle window is suspended only by a face-enrolment
            // workflow.  Alarm repetition is handled by ReminderCoordinator
            // and never participates in this timer.
            if (!face_enrollment_active &&
                device_state_ == kDeviceStateListening && listening_start_tick_ != 0) {
                uint32_t now = xTaskGetTickCount();
                if ((now - listening_start_tick_) >= pdMS_TO_TICKS(listening_timeout_ms_)) {
                    uint32_t used_timeout = listening_timeout_ms_;
                    listening_start_tick_ = 0;
                    ListeningReason reason = listening_reason_;
                    Schedule([this, used_timeout, reason]() {
                        if (device_state_ != kDeviceStateListening) {
                            return;
                        }
                        ESP_LOGI(TAG, "Interaction idle after %lu ms, returning to idle",
                                 (unsigned long)used_timeout);
                        if (reason == kListeningReasonReminder) {
                            // The card lifetime, not a chat control frame,
                            // owns this listening window.  Report the close
                            // before returning the device to normal idle.
                            EndReminderInteraction("", 0, "timeout");
                            ReminderCoordinator::GetInstance().Tick(
                                time(nullptr), true);
                            return;
                        }
                        if (awaiting_server_reply_) {
                            awaiting_server_reply_ = false;
                            // The firmware has no offline speech synthesiser.
                            // Alert + local error sound is the reliable local
                            // fallback when the network/LLM does not answer.
#if CONFIG_LANGUAGE_ZH_CN
                            Alert(Lang::Strings::ERROR,
                                  Lang::Strings::SERVER_RESPONSE_TIMEOUT, "sad",
                                  Lang::Sounds::OGG_SERVER_RESPONSE_TIMEOUT);
#else
                            Alert(Lang::Strings::ERROR,
                                  "网络暂时异常，请稍后再试", "sad",
                                  Lang::Sounds::OGG_EXCLAMATION);
#endif
                            // The error result is itself a foreground
                            // interaction.  Keep the normal 30-second window
                            // so the user can retry or touch the device before
                            // the microphone and UI return to idle.
                            listening_start_tick_ = xTaskGetTickCount();
                            listening_timeout_ms_ = LISTENING_TIMEOUT_MS;
                            return;
                        }
                        SetDeviceState(kDeviceStateIdle);
                        if (protocol_ && protocol_->IsAudioChannelOpened()) {
                            protocol_->CloseAudioChannel();
                        }
                    });
                }
            }
            
            // Skip status bar updates while provisioning or upgrading.
            if (device_state_ != kDeviceStateWifiConfiguring &&
                device_state_ != kDeviceStateUpgrading) {
                display->UpdateStatusBar();
            }

            display->TickStandbyClock(
                device_state_ == kDeviceStateIdle && !face_enrollment_active &&
                !IsReminderInteractionActive() && !IsSpineOtaRunning() &&
                !IsWallpaperOtaRunning() && !tts_stream_active_.load() &&
                audio_service_.IsIdle() && audio_service_.IsPlaybackDrained() &&
                !CameraManager::GetInstance().IsForegroundOperationActive(),
                !CameraManager::GetInstance().IsOperationActive());

            UserContext::GetInstance().TickSessionCleanup();
            time_t reminder_now = time(nullptr);
            if (reminder_now > 1000000000L) {
                ReminderCoordinator::GetInstance().Tick(
                    reminder_now, device_state_ == kDeviceStateIdle);
            }

            static MinuteScheduler minute_scheduler;
            const auto due_minutes = minute_scheduler.Advance(time(nullptr));
            if (due_minutes.first <= due_minutes.last) {
                for (time_t tick_minute = due_minutes.first; tick_minute <= due_minutes.last; ++tick_minute) {
                    time_t now = tick_minute * 60;
                    struct tm t;
                    localtime_r(&now, &t);

                    const int day_key =
                        (t.tm_year + 1900) * 1000 + t.tm_yday;
                    char occurrence[24];
                    snprintf(occurrence, sizeof(occurrence),
                             "%04d%03d-%02d%02d",
                             t.tm_year + 1900, t.tm_yday,
                             t.tm_hour, t.tm_min);

                    AlarmManager::GetInstance().CheckAndFire(
                        t.tm_hour, t.tm_min, t.tm_wday, day_key,
                        [now, occurrence](const Alarm& alarm) {
                            const std::string& creator =
                                alarm.creator_person_id.empty()
                                    ? alarm.owner_user_id
                                    : alarm.creator_person_id;
                            ReminderCoordinator::GetInstance().EnqueueAlarm(
                                alarm.id, creator, alarm.label, now,
                                occurrence, alarm.recipient_person_id,
                                creator);
                        });

                    NoteManager::GetInstance().CheckAndRemind(
                        static_cast<uint32_t>(now),
                        [](const Note& note) {
                            const std::string& creator =
                                note.creator_person_id.empty()
                                    ? note.owner_user_id
                                    : note.creator_person_id;
                            return ReminderCoordinator::GetInstance().EnqueueNote(
                                note.id, creator, note.text,
                                static_cast<time_t>(note.remind_at),
                                std::to_string(note.remind_at),
                                note.priority, note.attention_policy,
                                note.pre_alert_minutes,
                                note.recipient_person_id, creator,
                                note.recipient_display_name_snapshot);
                        });

                    HabitManager::GetInstance().CheckAndFire(
                        t.tm_hour, t.tm_min, day_key,
                        [now, occurrence](const Habit& habit) {
                            const std::string& creator =
                                habit.creator_person_id.empty()
                                    ? habit.owner_user_id
                                    : habit.creator_person_id;
                            return ReminderCoordinator::GetInstance().EnqueueHabit(
                                habit.id, creator, habit.description, habit.occurrence_at - habit.advance_minutes * 60,
                                std::to_string(habit.occurrence_at), habit.recipient_person_id,
                                creator);
                        }, now);

                    if (t.tm_hour == 3 && t.tm_min == 0 && last_prune_day_ != t.tm_yday) {
                        last_prune_day_ = t.tm_yday;
                        BehaviorLogger::GetInstance().Prune();
                        ProactiveManager::GetInstance().ClearDailyState();
                        NoteManager::GetInstance().PruneExpired((uint32_t)now);
                        if (device_state_ == kDeviceStateIdle) {
                            StartChatWithText(
                                "[MAINTENANCE] Please call habit.analyze for the last 7 days. "
                                "If patterns are found, call habit.learn for each one. "
                                "Do not clear logs directly or announce the result to the user.");
                        }
                    }
                }
            }

            // Application-level Keep-Alive heartbeat to prevent TCP connection drops
            if (clock_ticks_ % 20 == 0) {
                if (protocol_ && protocol_->IsAudioChannelOpened()) {
                    if (device_state_ == kDeviceStateIdle ||
                        device_state_ == kDeviceStateListening ||
                        device_state_ == kDeviceStateSpeaking) {
                        ESP_LOGI(TAG, "[WS_DIAG] app_ping tick=%lu",
                                 (unsigned long)clock_ticks_);
                        protocol_->SendText("{\"type\":\"ping\"}");
                    }
                }
            }

            // [WS_DL] 下行音频链路统计：仅在 Speaking 时每秒最多一条（clock tick 每秒触发）。
            if (device_state_ == kDeviceStateSpeaking) {
                AudioService::DownlinkStats ds;
                audio_service_.GetDownlinkStats(ds);
                ESP_LOGI(TAG, "[WS_DL] rx=%lu decode_q=%u playback_q=%u decode_drop=%lu decode_ok=%lu decode_fail=%lu underrun=%lu",
                         (unsigned long)ds.rx_frames,
                         (unsigned)ds.decode_queue, (unsigned)ds.playback_queue,
                         (unsigned long)ds.decode_drop, (unsigned long)ds.decode_ok,
                         (unsigned long)ds.decode_fail, (unsigned long)ds.underrun);
            }
            UpdateTtsPlayback();
        }
    }
}
void Application::OnWakeWordDetected() {
    Board::GetInstance().GetDisplay()->WakeFromStandbyClock();
    if (!protocol_) {
        DropWakeWord("no_protocol", true);
        return;
    }

    if (FaceEnrollmentManager::GetInstance().IsActive()) {
        DropWakeWord("face_enrollment_active", true);
        return;
    }

    if (device_state_ == kDeviceStateListening) {
        ESP_LOGW(TAG, "Wake word received while already listening; ignoring duplicate trigger");
        Schedule([this]() { EnsureListeningAudio(); });
        return;
    }

    if (device_state_ == kDeviceStateSpeaking) {
        Schedule([this]() {
            AbortSpeaking(kAbortReasonWakeWordDetected);
            ResumeListeningAfterWakeInterrupt();
        });
        return;
    }

    if (device_state_ == kDeviceStateUpgrading ||
        device_state_ == kDeviceStateFatalError ||
        device_state_ == kDeviceStateWifiConfiguring) {
        DropWakeWord("unsupported_state", true);
        return;
    }

    auto& coord = ProactiveWakeCoordinator::GetInstance();
    if (coord.HasPendingGreeting()) {
        coord.DiscardPendingGreeting("manual_wake_priority");
    }
    {
        std::lock_guard<std::mutex> lock(main_ws_request_mutex_);
        ClearProactiveChatPendingLocked();
    }

    if (protocol_->IsAudioChannelOpened()) {
        audio_service_.EncodeWakeWord();
        CompleteWakeWordFlow(audio_service_.GetLastWakeWord());
        return;
    }

    QueueWakeWordChannelOpen();
}

void Application::DropWakeWord(const char* reason, bool reenable_latch) {
    if (reenable_latch) {
        audio_service_.EnableWakeWordDetection(true);
    }
    ESP_LOGW(TAG, "Wake word dropped state=%s reason=%s latch_reenabled=%d",
             DeviceStateName(device_state_), reason ? reason : "-",
             reenable_latch ? 1 : 0);
}

void Application::RecoverWakeWordDetection(const char* reason) {
    audio_service_.EnableWakeWordDetection(true);
    ESP_LOGI(TAG, "Wake word latch recovered reason=%s latch_reenabled=1",
             reason ? reason : "-");
}

void Application::QueueWakeWordChannelOpen() {
    audio_service_.EncodeWakeWord();
    if (device_state_ != kDeviceStateConnecting) {
        SetDeviceState(kDeviceStateConnecting);
    }
    ArmConnectingTimeout();

    MainWsPendingIntent intent;
    intent.has_intent = true;
    intent.wake_from_audio = true;
    intent.action = PendingMainWsAction::kWakeWordFlow;
    const auto outcome = SubmitMainWsOpenRequest(
        main_ws_open::Source::kManual, /*require_presence=*/false, intent);

    if (outcome.result == MainWsOpenRequestResult::kFailedNoProtocol) {
        DropWakeWord("channel_open_failed", true);
        RecoverFromFailedChannelOpen("wake_queue_failed");
        return;
    }

    bool pending_wake = outcome.pending_applied;
    if (!pending_wake) {
        std::lock_guard<std::mutex> lock(main_ws_request_mutex_);
        pending_wake =
            pending_main_ws_action_ == PendingMainWsAction::kWakeWordFlow;
    }
    if (!pending_wake &&
        outcome.result != MainWsOpenRequestResult::kAlreadyOpen) {
        DropWakeWord("pending_not_applied", true);
    }
}

void Application::ArmConnectingTimeout() {
    if (connecting_timer_handle_ == nullptr) {
        return;
    }
    esp_timer_stop(connecting_timer_handle_);
    esp_timer_start_once(
        connecting_timer_handle_,
        static_cast<uint64_t>(CONNECTING_TIMEOUT_MS) * 1000ULL);
}

void Application::CancelConnectingTimeout() {
    if (connecting_timer_handle_ != nullptr) {
        esp_timer_stop(connecting_timer_handle_);
    }
}

void Application::OnConnectingTimeout() {
    if (device_state_ != kDeviceStateConnecting) {
        return;
    }
    RecoverFromFailedChannelOpen("connecting timeout");
}

void Application::RecoverFromFailedChannelOpen(const char* reason) {
    ESP_LOGW(TAG, "%s -> idle", reason ? reason : "channel_open_failed");
    ClearPendingMainWsActionLocked();
    ProactiveWakeCoordinator::GetInstance().CancelActiveFlow(
        reason ? reason : "channel_open_failed");
    SetDeviceState(kDeviceStateIdle);
    RecoverWakeWordDetection(reason);
}

void Application::AbortSpeaking(AbortReason reason) {
    ESP_LOGI(TAG, "Abort speaking");
    UserContext::GetInstance().ClearCurrentSpeakerUser();
    aborted_ = true;
    // Interruption must start the next stream from a clean decoder/playback
    // queue.  Leaving old packets here was the source of decode_drop bursts
    // and text/audio from different turns being mixed together.
    audio_service_.ResetDecoder();
    if (active_tts_generation_ != 0) {
        tts_closed_generation_ = active_tts_generation_;
    }
    ClearTtsStream(true);
    if (protocol_) {
        protocol_->SendAbortSpeaking(reason);
    }
}

void Application::ResumeListeningAfterWakeInterrupt() {
    if (!protocol_ || !protocol_->IsAudioChannelOpened()) {
        ESP_LOGW(TAG, "[WAKE_INTERRUPT] event=resume_failed reason=audio_channel_closed");
        DropWakeWord("interrupt_channel_closed", true);
        RecoverFromFailedChannelOpen("wake_interrupt_channel_closed");
        return;
    }
    listening_reason_ = kListeningReasonWakeWord;
    CompleteWakeWordFlow(audio_service_.GetLastWakeWord());
    ESP_LOGI(TAG, "[WAKE_INTERRUPT] event=resumed_listening");
}

void Application::ResumeListeningAfterUserInterrupt(ListeningReason reason) {
    if (!protocol_ || !protocol_->IsAudioChannelOpened()) {
        ESP_LOGW(TAG, "[ABORT] event=resume_failed reason=audio_channel_closed");
        RecoverFromFailedChannelOpen("abort_resume_channel_closed");
        return;
    }
    if (reason != kListeningReasonUnknown) {
        listening_reason_ = reason;
    } else if (listening_reason_ == kListeningReasonUnknown) {
        listening_reason_ = kListeningReasonSystem;
    }
    SetListeningMode(aec_mode_ == kAecOff ? kListeningModeAutoStop
                                          : kListeningModeRealtime);
    ESP_LOGI(TAG, "[ABORT] event=resumed_listening reason=%d",
             static_cast<int>(listening_reason_));
}

void Application::SetListeningMode(ListeningMode mode) {
    listening_mode_ = mode;
    listening_timeout_ms_ = LISTENING_TIMEOUT_MS;
    audio_service_.ResetUploadQueues();
    audio_service_.LogUploadStats("listen_start");
    ESP_LOGI(TAG, "[WS_AUDIO_UP] session=%s reason=listen_start",
             protocol_ ? protocol_->session_id().c_str() : "-");
    if (device_state_ == kDeviceStateListening) {
        ArmListeningAudio();
    } else {
        SetDeviceState(kDeviceStateListening);
    }
}

void Application::ArmListeningAudio() {
    UserContext::GetInstance().ClearCurrentSpeakerUser();
    listening_start_tick_ = xTaskGetTickCount();
    audio_service_.EnableVoiceProcessing(true);
    audio_service_.EnableWakeWordDetection(false);
    if (protocol_) protocol_->SendStartListening(listening_mode_);
    audio_service_.LogUploadStats("listen_armed");
}

void Application::EnsureListeningAudio() {
    if (device_state_ != kDeviceStateListening ||
        FaceEnrollmentManager::GetInstance().IsActive()) return;
    if (!audio_service_.IsAudioProcessorRunning() ||
        !audio_service_.IsAudioSubsystemReady() || audio_service_.IsWakeWordRunning()) {
        ESP_LOGW(TAG, "[WS_AUDIO_UP] event=repair_listening_audio");
        SetListeningMode(listening_mode_);
    }
    ResetListeningTimeout(false);
}

void Application::SetDeviceState(DeviceState state) {
    if (device_state_ == state) {
        return;
    }
    
    DeviceState previous_state = device_state_;
    if (previous_state == kDeviceStateListening) {
        listening_start_tick_ = 0;
        listening_reason_ = kListeningReasonUnknown;
    }
    if (state == kDeviceStateListening) {
        listening_start_tick_ = xTaskGetTickCount();
    }
    if (previous_state == kDeviceStateConnecting &&
        state != kDeviceStateConnecting) {
        CancelConnectingTimeout();
    }

    clock_ticks_ = 0;
    device_state_ = state;
    ESP_LOGI(TAG, "STATE: %s", STATE_STRINGS[device_state_]);

    ReminderControlClient::GetInstance().OnDeviceStateChanged(state);

    if (state == kDeviceStateIdle && previous_state != kDeviceStateIdle) {
        Schedule([this]() { FlushPendingReminders(); });
    }

    // Send the state change event
    DeviceStateEventManager::GetInstance().PostStateChangeEvent(previous_state, state);

    auto& board = Board::GetInstance();
    auto display = board.GetDisplay();
    auto led = board.GetLed();
    led->OnStateChanged();
    display->WakeFromStandbyClock();
    switch (state) {
        case kDeviceStateUnknown:
        case kDeviceStateIdle:
            display->SetStatus(Lang::Strings::STANDBY);
            display->SetEmotion("neutral");
            audio_service_.EnableVoiceProcessing(false);
            audio_service_.ResetUploadQueues();
            audio_service_.EnableWakeWordDetection(true);
            ESP_LOGI(TAG, "Idle audio mode restored: voice processing off, wake word on");
            break;
        case kDeviceStateConnecting:
            ArmConnectingTimeout();
            display->SetStatus(Lang::Strings::CONNECTING);
            display->SetEmotion("doubt");
            display->SetChatMessage("system", "");
            break;
        case kDeviceStateListening:
            display->SetStatus(Lang::Strings::LISTENING);
            display->SetEmotion("awe");

            // Always (re)arm uplink. Skipping this when the processor is still
            // running was dropping listen start / EnableVoiceProcessing after
            // barge-in, especially in realtime AEC mode.
            ArmListeningAudio();
            break;
        case kDeviceStateSpeaking:
            display->SetStatus(Lang::Strings::SPEAKING);
            if (!last_llm_emotion_.empty()) {
                display->SetEmotion(last_llm_emotion_.c_str());
            } else {
                display->SetEmotion("happy");
            }

            if (listening_mode_ != kListeningModeRealtime) {
                audio_service_.EnableVoiceProcessing(false);
                // Discard uplink already queued for the previous listen so it
                // cannot ride along under a speaking turn. Realtime/AEC keeps
                // its existing uplink path and must not lose that queue here.
                // Do not invent a listen:stop: server semantics for an empty
                // stop are unclear and may submit extra ASR / interrupt TTS.
                audio_service_.ResetUploadQueues();
                // Only AFE wake word can be detected in speaking mode
                audio_service_.EnableWakeWordDetection(audio_service_.IsAfeWakeWord());
            }
            break;
        default:
            // Do nothing
            break;
    }
}

void Application::Reboot() {
    ESP_LOGI(TAG, "Rebooting...");
    // Disconnect the audio channel
    if (protocol_ && protocol_->IsAudioChannelOpened()) {
        protocol_->CloseAudioChannel();
    }
    protocol_.reset();
    audio_service_.Stop();

    // Join raster work and drain snapshots/DMA before a role-change restart.
    if (auto* display=Board::GetInstance().GetDisplay()) {
        display->SetPowerSaveMode(true);
    }

    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_restart();
}

bool Application::IsSpineOtaRunning() const {
    return SpineOta::GetInstance().IsRunning();
}

bool Application::IsWallpaperOtaRunning() const {
    return WallpaperOta::GetInstance().IsRunning();
}

void Application::BeginSpineOtaAckWait(const std::string& task_id) {
    std::lock_guard<std::mutex> lock(ota_ack_mutex_);
    ota_ack_task_id_ = task_id;
    ota_ack_completed_ = false;
    ota_ack_pending_ = true;
}

bool Application::FinishSpineOtaAckWait(int timeout_ms) {
    std::unique_lock<std::mutex> lock(ota_ack_mutex_);
    if (!ota_ack_pending_) {
        return ota_ack_completed_;
    }
    ota_ack_cv_.wait_for(lock, std::chrono::milliseconds(timeout_ms),
                         [this]() { return !ota_ack_pending_; });
    const bool completed = ota_ack_completed_;
    ota_ack_pending_ = false;
    return completed;
}

void Application::CancelSpineOtaAckWait() {
    std::lock_guard<std::mutex> lock(ota_ack_mutex_);
    ota_ack_pending_ = false;
    ota_ack_completed_ = false;
    ota_ack_cv_.notify_all();
}

void Application::OnSpineOtaAck(const cJSON* root) {
    cJSON* task_id = cJSON_GetObjectItem(root, "task_id");
    cJSON* status = cJSON_GetObjectItem(root, "status");
    if (!cJSON_IsString(task_id) || !cJSON_IsString(status)) {
        ESP_LOGW(TAG, "[SpineOta] malformed spine_ota_ack");
        return;
    }
    const std::string tid = task_id->valuestring;
    const std::string st = status->valuestring;
    ESP_LOGI(TAG, "[SpineOta] received spine_ota_ack task_id=%s status=%s",
             tid.c_str(), st.c_str());
    std::lock_guard<std::mutex> lock(ota_ack_mutex_);
    if (!ota_ack_pending_) {
        ESP_LOGW(TAG, "[SpineOta] spine_ota_ack ignored (no waiter) task_id=%s", tid.c_str());
        return;
    }
    if (tid == ota_ack_task_id_ && st == "completed") {
        ota_ack_completed_ = true;
        ota_ack_pending_ = false;
        ota_ack_cv_.notify_all();
    } else {
        ESP_LOGW(TAG, "[SpineOta] spine_ota_ack mismatch expected=%s status=%s",
                 ota_ack_task_id_.c_str(), st.c_str());
    }
}

void Application::HandleUpdateSpine(const cJSON* root) {
    // Status sender. Keeps the WebSocket control channel open; never closes it.
    // Returns the SendText result and logs task_id/phase/result (no sensitive fields).
    auto send_status = [this](const std::string& task_id, const std::string& pack_id,
                              const char* phase, int progress, const char* error,
                              bool duplicate = false, const char* reason = nullptr) -> bool {
        if (!protocol_ || !protocol_->IsAudioChannelOpened()) {
            ESP_LOGW(TAG, "[SpineOta] send_status skipped task=%s phase=%s err=%s (ws not open)",
                     task_id.c_str(), phase, error ? error : "none");
            return false;
        }
        cJSON* msg = cJSON_CreateObject();
        cJSON_AddStringToObject(msg, "type", "spine_ota_status");
        cJSON_AddStringToObject(msg, "task_id", task_id.c_str());
        cJSON_AddStringToObject(msg, "pack_id", pack_id.c_str());
        cJSON_AddStringToObject(msg, "phase", phase);
        cJSON_AddNumberToObject(msg, "progress", progress);
        if (error) {
            cJSON_AddStringToObject(msg, "error", error);
        } else {
            cJSON_AddNullToObject(msg, "error");
        }
        if (reason) {
            cJSON_AddStringToObject(msg, "reason", reason);
            cJSON_AddBoolToObject(msg, "not_accepted", true);
        }
        if (duplicate) {
            cJSON_AddBoolToObject(msg, "duplicate", true);
        }
        char* text = cJSON_PrintUnformatted(msg);
        if (text == nullptr) {
            cJSON_Delete(msg);
            ESP_LOGE(TAG, "[SpineOta] send_status encode failed task=%s phase=%s",
                     task_id.c_str(), phase);
            return false;
        }
        const bool ok = protocol_->SendText(text);
        cJSON_free(text);
        cJSON_Delete(msg);
        ESP_LOGI(TAG, "[SpineOta] send_status task=%s phase=%s progress=%d err=%s sent=%d",
                 task_id.c_str(), phase, progress, error ? error : "none", ok ? 1 : 0);
        return ok;
    };

    SpineOtaTask task;
    SpineOtaError perr = SpineOtaError::kBundle;
    if (!SpineOta::ParseTask(root, task, perr)) {
        ESP_LOGW(TAG, "update_spine parse failed: %s", SpineOtaErrorToString(perr));
        cJSON* tid = cJSON_GetObjectItem(root, "task_id");
        cJSON* pid = cJSON_GetObjectItem(root, "pack_id");
        if (cJSON_IsString(tid)) {
            send_status(tid->valuestring,
                        cJSON_IsString(pid) ? pid->valuestring : "",
                        "failed", 0, SpineOtaErrorToString(perr));
        }
        return;
    }

    // Reject before acquire if another upgrade/activation path is active.
    if (device_state_ == kDeviceStateUpgrading ||
        device_state_ == kDeviceStateActivating ||
        device_state_ == kDeviceStateStarting ||
        device_state_ == kDeviceStateWifiConfiguring) {
        ESP_LOGW(TAG, "update_spine rejected pre-acquire: E_BUSY state=%d",
                 static_cast<int>(device_state_));
        send_status(task.task_id, task.pack_id, "failed", 0, "E_BUSY", false, "device_state_ineligible");
        return;
    }

    auto display = Board::GetInstance().GetDisplay();
    // Success-status delivery result captured from the kSuccess Report inside
    // RunTask. On failure the committed slot is kept; the success path falls back
    // to the existing "ACK timeout -> reboot once" strategy and never re-downloads.
    bool success_send_ok = true;
    auto status_cb =
        [this, display, send_status, &success_send_ok](SpineOtaPhase phase, int progress, SpineOtaError error,
                                     const std::string& task_id, const std::string& pack_id) {
            const char* err_str = SpineOtaErrorToString(error);
            // Phase telemetry (received/accepted/audio_stopped are logged by the caller).
            const char* phase_log = "unknown";
            switch (phase) {
                case SpineOtaPhase::kIdle:       phase_log = "idle"; break;
                case SpineOtaPhase::kWaiting:    phase_log = "waiting"; break;
                case SpineOtaPhase::kDownloading: phase_log = "download"; break;
                case SpineOtaPhase::kVerifying:  phase_log = "verify"; break;
                case SpineOtaPhase::kApplying:   phase_log = "commit"; break;
                case SpineOtaPhase::kSuccess:    phase_log = "success_sent"; break;
                case SpineOtaPhase::kFailed:     phase_log = "failed"; break;
            }
            ESP_LOGI(TAG, "[SpineOta] phase=%s task_id=%s progress=%d", phase_log,
                     task_id.c_str(), progress);
            if (display) {
                const char* title = "更换角色";
                char detail[96] = {0};
                int bar = progress;
                switch (phase) {
                    case SpineOtaPhase::kWaiting:
                        title = "正在下载角色";
                        snprintf(detail, sizeof(detail), "准备中…");
                        bar = 0;
                        break;
                    case SpineOtaPhase::kDownloading:
                        title = "正在下载角色";
                        snprintf(detail, sizeof(detail), "%d%%", progress);
                        break;
                    case SpineOtaPhase::kVerifying:
                        title = "正在下载角色";
                        snprintf(detail, sizeof(detail), "校验中…");
                        bar = 100;
                        break;
                    case SpineOtaPhase::kApplying:
                        title = "更换角色";
                        snprintf(detail, sizeof(detail), "正在应用…");
                        bar = 100;
                        break;
                    case SpineOtaPhase::kSuccess:
                        title = "更换角色";
                        snprintf(detail, sizeof(detail), "更换成功，即将重启");
                        bar = 100;
                        break;
                    case SpineOtaPhase::kFailed:
                        title = "更换角色";
                        snprintf(detail, sizeof(detail), "失败: %s",
                                 err_str ? err_str : "unknown");
                        bar = -1;
                        break;
                    default:
                        break;
                }
                display->ShowSpineOtaStatus(title, detail, bar);
            }
            const bool sent = send_status(task_id, pack_id, SpineOtaPhaseToString(phase), progress, err_str);
            if (phase == SpineOtaPhase::kSuccess) {
                success_send_ok = sent;
            }
        };

    // Atomic acquire BEFORE any security precheck / audio stop / UI / state changes.
    if (!SpineOta::GetInstance().TryAcquire(status_cb)) {
        ESP_LOGW(TAG, "update_spine rejected: E_BUSY (running)");
        // Do not touch audio, UI, callback, or device state of the in-flight task.
        // E_BUSY did not acquire — must not Release.
        send_status(task.task_id, task.pack_id, "failed", 0, "E_BUSY", false, "spine_task_running");
        return;
    }
    if (!TryAcquireVisualOta()) {
        // The per-feature lock succeeded, but wallpaper holds the shared flash
        // writer. Undo this partial acquire before reporting E_BUSY.
        SpineOta::GetInstance().Release();
        ESP_LOGW(TAG, "update_spine rejected: E_BUSY (wallpaper OTA running)");
        send_status(task.task_id, task.pack_id, "failed", 0, "E_BUSY", false, "wallpaper_resource_lock");
        return;
    }

    // Hold running=true until success reboot or failure cleanup finishes.
    // RunTask must not Release. If Reboot() unexpectedly returns, destructor frees the lock.
    struct SpineOtaRunGuard {
        bool armed = true;
        ~SpineOtaRunGuard() {
            if (armed) {
                SpineOta::GetInstance().Release();
                ReleaseVisualOta();
            }
        }
    } run_guard;

    // Full security precheck (HTTPS/host/role/size/min_fw/ES256) BEFORE the
    // idempotency shortcut, so a replayed duplicate task cannot skip validation.
    {
        std::string detail;
        SpineOtaError pre = SpineOta::Precheck(task, &detail);
        if (pre != SpineOtaError::kNone) {
            ESP_LOGE(TAG, "update_spine precheck failed %s (%s)",
                     SpineOtaErrorToString(pre), detail.c_str());
            send_status(task.task_id, task.pack_id, "failed", 0, SpineOtaErrorToString(pre));
            return;
        }
    }

    // Register the ACK waiter before any success frame can be emitted.
    BeginSpineOtaAckWait(task.task_id);

    // Acknowledge receipt immediately (control channel still open).
    ESP_LOGI(TAG, "[SpineOta] phase=accepted task_id=%s", task.task_id.c_str());
    const bool accepted_ok = send_status(task.task_id, task.pack_id, "accepted", 0, nullptr);
    if (!accepted_ok) {
        // The server never learned this task was accepted. Abort before touching
        // audio / download / slot / reboot so the server can re-deliver the task.
        // Audio, UI and device_state have not been modified yet, so nothing to
        // restore; just drop the waiter and release the acquire lock (run_guard).
        ESP_LOGE(TAG, "[SpineOta] accepted_send_failed task_id=%s action=abort_before_download",
                 task.task_id.c_str());
        CancelSpineOtaAckWait();
        return;  // run_guard releases the acquire lock.
    }

    // Idempotency: reuse the NVS fields written after a validated single-slot
    // role package is committed.
    Settings spine_nvs("spine", false);
    const std::string last_task_id = spine_nvs.GetString("last_task_id", "");
    const std::string last_role_id = spine_nvs.GetString("active_role_id", "");
    const std::string last_version = spine_nvs.GetString("active_version", "");
    const std::string last_sha256 = spine_nvs.GetString("last_sha256", "");

    if (!last_task_id.empty() && last_task_id == task.task_id) {
        // Content integrity: a replayed task_id must map to the exact content we
        // already committed. If role_id / version / sha256 differ, treat it as a
        // security error and reject instead of silently re-downloading or
        // re-slotting (the signature precheck above already passed, so this guards
        // against a server-side replay with conflicting metadata for the same id).
        if (last_role_id != task.role_id || last_version != task.version ||
            last_sha256 != task.sha256) {
            ESP_LOGE(TAG, "[SpineOta] task_id reuse with different content task=%s "
                     "committed=(role=%s ver=%s sha=%s) task=(role=%s ver=%s sha=%s)",
                     task.task_id.c_str(), last_role_id.c_str(), last_version.c_str(),
                     last_sha256.c_str(), task.role_id.c_str(), task.version.c_str(),
                     task.sha256.c_str());
            send_status(task.task_id, task.pack_id, "failed", 0, "E_TASK_MISMATCH");
            CancelSpineOtaAckWait();
            return;  // run_guard releases the acquire lock.
        }

        const bool running_dynamic = SpineAssets::GetInstance().uses_dynamic_partition();
        ESP_LOGI(TAG, "[SpineOta] duplicate task_id=%s (role=%s ver=%s) running_source=%s; resending success",
                 task.task_id.c_str(), last_role_id.c_str(), last_version.c_str(),
                 SpineAssets::GetInstance().active_label());
        const bool dup_success_ok = send_status(task.task_id, task.pack_id, "success", 100, nullptr, true);
        if (dup_success_ok) {
            ESP_LOGI(TAG, "[SpineOta] phase=success_sent task_id=%s duplicate=true", task.task_id.c_str());
        } else {
            ESP_LOGW(TAG, "[SpineOta] success_send_failed task_id=%s duplicate=true (commit kept; re-send on next delivery)",
                     task.task_id.c_str());
        }

        if (running_dynamic) {
            // Already running the committed role: confirm and return, no reboot.
            if (FinishSpineOtaAckWait(kSpineOtaAckTimeoutMs)) {
                ESP_LOGI(TAG, "[SpineOta] phase=ack_received task_id=%s (already active, no reboot)",
                         task.task_id.c_str());
            } else {
                ESP_LOGW(TAG, "[SpineOta] ack timeout task_id=%s (already active, no reboot)",
                         task.task_id.c_str());
            }
            return;  // run_guard releases the acquire lock.
        }

        // Committed slot not yet active (e.g. ACK lost before reboot): wait ACK, then reboot.
        if (FinishSpineOtaAckWait(kSpineOtaAckTimeoutMs)) {
            ESP_LOGI(TAG, "[SpineOta] phase=ack_received task_id=%s; rebooting", task.task_id.c_str());
        } else {
            ESP_LOGW(TAG, "[SpineOta] ack timeout task_id=%s; rebooting via local completion record",
                     task.task_id.c_str());
        }
        ESP_LOGI(TAG, "[SpineOta] phase=reboot task_id=%s", task.task_id.c_str());
        Reboot();
        ESP_LOGE(TAG, "Reboot returned after duplicate spine OTA ACK; releasing lock as fallback");
        return;
    }

    // Stop audio upload/listening but KEEP the WebSocket control channel open so
    // accepted/progress/success/failed status can still be reported to the server.
    audio_service_.Stop();
    audio_service_.ResetUploadQueues();
    audio_service_.EnableVoiceProcessing(false);
    audio_service_.EnableWakeWordDetection(false);
    ESP_LOGI(TAG, "[SpineOta] phase=audio_stopped task_id=%s", task.task_id.c_str());
    SetDeviceState(kDeviceStateUpgrading);

    const bool ok = SpineOta::GetInstance().RunTask(task);
    if (ok) {
        // RunTask already emitted kSuccess (status_cb -> send_status). Wait for the
        // server ACK before rebooting to activate the newly committed role.
        if (!success_send_ok) {
            ESP_LOGW(TAG, "[SpineOta] success_send_failed task_id=%s; commit already persisted, "
                     "waiting ACK (may timeout once) before reboot",
                     task.task_id.c_str());
        }
        if (display) {
            display->ShowSpineOtaStatus("更换角色", "更换成功，等待确认…", 100);
        }
        const bool acked = FinishSpineOtaAckWait(kSpineOtaAckTimeoutMs);
        if (acked) {
            ESP_LOGI(TAG, "[SpineOta] phase=ack_received task_id=%s; rebooting", task.task_id.c_str());
        } else {
            ESP_LOGW(TAG, "[SpineOta] ack timeout task_id=%s; rebooting via local completion record",
                     task.task_id.c_str());
        }
        if (display) {
            display->ShowSpineOtaStatus("更换角色", "更换成功，即将重启", 100);
        }
        vTaskDelay(pdMS_TO_TICKS(800));
        ESP_LOGI(TAG, "[SpineOta] phase=reboot task_id=%s", task.task_id.c_str());
        Reboot();
        // Safety net for tests / unexpected return: run_guard Release() on exit.
        ESP_LOGE(TAG, "Reboot returned after spine OTA success; releasing lock as fallback");
        return;
    }

    // Failure: cancel ACK wait, then restore audio/UI/state while still holding the lock.
    CancelSpineOtaAckWait();
    audio_service_.Start();
    Board::GetInstance().SetPowerSaveMode(true);
    if (device_state_ == kDeviceStateUpgrading) {
        SetDeviceState(kDeviceStateIdle);
    }
    if (display) {
        vTaskDelay(pdMS_TO_TICKS(2000));
        display->DismissSpineOtaStatus();
    }
    // run_guard Release() last on scope exit.
}

void Application::HandleUpdateWallpaper(const cJSON* root) {
    auto send_status = [this](const std::string& task_id, const std::string& pack_id,
                              const char* phase, int progress, const char* error,
                              bool duplicate = false) -> bool {
        if (!protocol_ || !protocol_->IsAudioChannelOpened()) return false;
        cJSON* message = cJSON_CreateObject();
        cJSON_AddStringToObject(message, "type", "wallpaper_ota_status");
        cJSON_AddStringToObject(message, "task_id", task_id.c_str());
        cJSON_AddStringToObject(message, "pack_id", pack_id.c_str());
        cJSON_AddStringToObject(message, "phase", phase);
        cJSON_AddNumberToObject(message, "progress", progress);
        if (error) cJSON_AddStringToObject(message, "error", error);
        else cJSON_AddNullToObject(message, "error");
        if (duplicate) cJSON_AddBoolToObject(message, "duplicate", true);
        char* text = cJSON_PrintUnformatted(message);
        const bool sent = text != nullptr && protocol_->SendText(text);
        if (text) cJSON_free(text);
        cJSON_Delete(message);
        ESP_LOGI(TAG, "[WallpaperOta] status task=%s phase=%s progress=%d sent=%d",
                 task_id.c_str(), phase, progress, sent ? 1 : 0);
        return sent;
    };

    WallpaperOtaTask task;
    WallpaperOtaError parse_error = WallpaperOtaError::kBundle;
    if (!WallpaperOta::ParseTask(root, task, parse_error)) {
        cJSON* task_id = cJSON_GetObjectItem(root, "task_id");
        cJSON* pack_id = cJSON_GetObjectItem(root, "pack_id");
        if (cJSON_IsString(task_id)) {
            send_status(task_id->valuestring,
                        cJSON_IsString(pack_id) ? pack_id->valuestring : "",
                        "failed", 0, WallpaperOtaErrorToString(parse_error));
        }
        return;
    }
    if (IsSpineOtaRunning() || device_state_ == kDeviceStateUpgrading ||
        device_state_ == kDeviceStateActivating || device_state_ == kDeviceStateStarting ||
        device_state_ == kDeviceStateWifiConfiguring) {
        send_status(task.task_id, task.pack_id, "failed", 0, "E_BUSY");
        return;
    }
    if (!TryAcquireVisualOta()) {
        send_status(task.task_id, task.pack_id, "failed", 0, "E_BUSY");
        return;
    }
    struct WallpaperVisualGateGuard {
        ~WallpaperVisualGateGuard() { ReleaseVisualOta(); }
    } visual_gate_guard;

    std::string precheck_detail;
    const WallpaperOtaError precheck = WallpaperOta::Precheck(task, &precheck_detail);
    if (precheck != WallpaperOtaError::kNone) {
        ESP_LOGW(TAG, "update_wallpaper precheck failed %s (%s)",
                 WallpaperOtaErrorToString(precheck), precheck_detail.c_str());
        send_status(task.task_id, task.pack_id, "failed", 0,
                    WallpaperOtaErrorToString(precheck));
        return;
    }

    auto display = Board::GetInstance().GetDisplay();
    auto status_cb = [display, send_status](WallpaperOtaPhase phase, int progress,
                                            WallpaperOtaError error,
                                            const std::string& task_id,
                                            const std::string& pack_id) {
        const char* error_text = WallpaperOtaErrorToString(error);
        if (display) {
            const char* title = "更换壁纸";
            char detail[96] = {};
            int bar = progress;
            switch (phase) {
                case WallpaperOtaPhase::kWaiting:
                    title = "正在下载壁纸"; snprintf(detail, sizeof(detail), "准备中…"); bar = 0; break;
                case WallpaperOtaPhase::kDownloading:
                    title = "正在下载壁纸"; snprintf(detail, sizeof(detail), "%d%%", progress); break;
                case WallpaperOtaPhase::kVerifying:
                    title = "正在下载壁纸"; snprintf(detail, sizeof(detail), "校验中…"); bar = 100; break;
                case WallpaperOtaPhase::kApplying:
                    snprintf(detail, sizeof(detail), "正在应用…"); bar = 100; break;
                case WallpaperOtaPhase::kSuccess:
                    snprintf(detail, sizeof(detail), "更换成功，即将重启"); bar = 100; break;
                case WallpaperOtaPhase::kFailed:
                    snprintf(detail, sizeof(detail), "失败: %s", error_text); bar = -1; break;
                default:
                    break;
            }
            display->ShowSpineOtaStatus(title, detail, bar);
        }
        send_status(task_id, pack_id, WallpaperOtaPhaseToString(phase), progress, error_text);
    };
    // The global visual gate is already held, so the per-feature lock can be
    // claimed without a second spine/wallpaper writer racing this task.
    if (!WallpaperOta::GetInstance().TryAcquire(status_cb)) {
        send_status(task.task_id, task.pack_id, "failed", 0, "E_BUSY");
        return;
    }
    struct WallpaperOtaExecutionGuard {
        ~WallpaperOtaExecutionGuard() { WallpaperOta::GetInstance().Release(); }
    } execution_guard;

    BeginSpineOtaAckWait(task.task_id);
    if (!send_status(task.task_id, task.pack_id, "accepted", 0, nullptr)) {
        CancelSpineOtaAckWait();
        return;
    }

    Settings settings("wallpaper", false);
    const std::string last_task = settings.GetString("last_task_id");
    if (!last_task.empty() && last_task == task.task_id) {
        if (settings.GetString("active_pack_id") != task.pack_id ||
            settings.GetString("active_version") != task.version ||
            settings.GetString("last_sha256") != task.sha256) {
            send_status(task.task_id, task.pack_id, "failed", 0, "E_TASK_MISMATCH");
            CancelSpineOtaAckWait();
            return;
        }
        send_status(task.task_id, task.pack_id, "success", 100, nullptr, true);
        FinishSpineOtaAckWait(kSpineOtaAckTimeoutMs);
        if (WallpaperAssets::GetInstance().ready()) return;
        Reboot();
        return;
    }

    audio_service_.Stop();
    audio_service_.ResetUploadQueues();
    audio_service_.EnableVoiceProcessing(false);
    audio_service_.EnableWakeWordDetection(false);
    SetDeviceState(kDeviceStateUpgrading);
    const bool ok = WallpaperOta::GetInstance().RunTask(task);
    if (ok) {
        if (display) display->ShowSpineOtaStatus("更换壁纸", "更换成功，等待确认…", 100);
        FinishSpineOtaAckWait(kSpineOtaAckTimeoutMs);
        if (display) display->ShowSpineOtaStatus("更换壁纸", "更换成功，即将重启", 100);
        vTaskDelay(pdMS_TO_TICKS(800));
        Reboot();
        return;
    }
    CancelSpineOtaAckWait();
    audio_service_.Start();
    Board::GetInstance().SetPowerSaveMode(true);
    if (device_state_ == kDeviceStateUpgrading) SetDeviceState(kDeviceStateIdle);
    if (display) {
        vTaskDelay(pdMS_TO_TICKS(2000));
        display->DismissSpineOtaStatus();
    }
}

bool Application::UpgradeFirmware(Ota& ota, const std::string& url) {
    auto& board = Board::GetInstance();
    auto display = board.GetDisplay();
    
    // Use provided URL or get from OTA object
    std::string upgrade_url = url.empty() ? ota.GetFirmwareUrl() : url;
    std::string version_info = url.empty() ? ota.GetFirmwareVersion() : "(Manual upgrade)";
    
    // Close audio channel if it's open
    if (protocol_ && protocol_->IsAudioChannelOpened()) {
        ESP_LOGI(TAG, "Closing audio channel before firmware upgrade");
        protocol_->CloseAudioChannel();
    }
    ESP_LOGI(TAG, "Starting firmware upgrade from URL: %s", upgrade_url.c_str());
    
    Alert(Lang::Strings::OTA_UPGRADE, Lang::Strings::UPGRADING, "download", Lang::Sounds::OGG_UPGRADE);
    vTaskDelay(pdMS_TO_TICKS(3000));

    SetDeviceState(kDeviceStateUpgrading);
    
    std::string message = std::string(Lang::Strings::NEW_VERSION) + version_info;
    display->SetChatMessage("system", message.c_str());

    board.SetPowerSaveMode(false);
    audio_service_.Stop();
    vTaskDelay(pdMS_TO_TICKS(1000));

    bool upgrade_success = ota.StartUpgradeFromUrl(upgrade_url, [display](int progress, size_t speed) {
        std::thread([display, progress, speed]() {
            char buffer[32];
            snprintf(buffer, sizeof(buffer), "%d%% %uKB/s", progress, speed / 1024);
            display->SetChatMessage("system", buffer);
        }).detach();
    });

    if (!upgrade_success) {
        // Upgrade failed, restart audio service and continue running
        ESP_LOGE(TAG, "Firmware upgrade failed, restarting audio service and continuing operation...");
        audio_service_.Start(); // Restart audio service
        board.SetPowerSaveMode(true); // Restore power save mode
        Alert(Lang::Strings::ERROR, Lang::Strings::UPGRADE_FAILED, "sad", Lang::Sounds::OGG_EXCLAMATION);
        vTaskDelay(pdMS_TO_TICKS(3000));
        return false;
    } else {
        // Upgrade success, reboot immediately
        ESP_LOGI(TAG, "Firmware upgrade successful, rebooting...");
        display->SetChatMessage("system", "Upgrade successful, rebooting...");
        vTaskDelay(pdMS_TO_TICKS(1000)); // Brief pause to show message
        Reboot();
        return true;
    }
}

void Application::WakeWordInvoke(const std::string& wake_word) {
    Board::GetInstance().GetDisplay()->WakeFromStandbyClock();
    if (!protocol_) {
        return;
    }
    if (FaceEnrollmentManager::GetInstance().IsActive()) {
        ESP_LOGI(TAG, "[FACE_ENROLL] event=wake_invoke_ignored");
        return;
    }

    if (device_state_ == kDeviceStateIdle) {
        audio_service_.EncodeWakeWord();

        if (!protocol_->IsAudioChannelOpened()) {
            SetDeviceState(kDeviceStateConnecting);
            MainWsPendingIntent intent;
            intent.has_intent = true;
            intent.wake_word = wake_word;
            intent.action = PendingMainWsAction::kWakeWordFlow;
            SubmitMainWsOpenRequest(main_ws_open::Source::kManual,
                                    /*require_presence=*/false, intent);
            return;
        }

        CompleteWakeWordFlow(wake_word);
    } else if (device_state_ == kDeviceStateSpeaking) {
        Schedule([this, wake_word]() {
            AbortSpeaking(kAbortReasonWakeWordDetected);
            if (!protocol_ || !protocol_->IsAudioChannelOpened()) {
                ESP_LOGW(TAG, "[WAKE_INTERRUPT] event=resume_failed reason=audio_channel_closed");
                RecoverFromFailedChannelOpen("wake_invoke_channel_closed");
                return;
            }
            listening_reason_ = kListeningReasonWakeWord;
            CompleteWakeWordFlow(wake_word);
        });
    } else if (device_state_ == kDeviceStateListening) {   
        ESP_LOGW(TAG, "WakeWordInvoke received while already listening; ignoring duplicate trigger");
        Schedule([this]() { EnsureListeningAudio(); });
    }
}

void Application::StartChatWithText(const std::string& text) {
    if (!protocol_ || device_state_ != kDeviceStateIdle) {
        ESP_LOGW(TAG, "StartChatWithText: not idle or no protocol");
        return;
    }
    if (!protocol_->IsAudioChannelOpened()) {
        SetDeviceState(kDeviceStateConnecting);
        MainWsPendingIntent intent;
        intent.has_intent = true;
        intent.action = PendingMainWsAction::kInjectChatText;
        intent.chat_text = text;
        const auto outcome = SubmitMainWsOpenRequest(
            main_ws_open::Source::kGreeting, /*require_presence=*/true, intent);
        if (!outcome.pending_applied &&
            outcome.result == MainWsOpenRequestResult::kRejectedLowerPriority) {
            SetDeviceState(kDeviceStateIdle);
        }
        return;
    }

    SetDeviceState(kDeviceStateIdle);

    cJSON* root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "session_id", protocol_->session_id().c_str());
    cJSON_AddStringToObject(root, "type", "listen");
    cJSON_AddStringToObject(root, "state", "detect");
    cJSON_AddStringToObject(root, "text", text.c_str());
    char* json_str = cJSON_PrintUnformatted(root);
    if (json_str != nullptr) {
        protocol_->SendText(json_str);
        cJSON_free(json_str);
    }
    cJSON_Delete(root);
    ESP_LOGI(TAG, "StartChatWithText injected: len=%u",
             static_cast<unsigned>(text.size()));
}

bool Application::OpenMainAudioChannelExclusive() {
    std::lock_guard<std::mutex> lock(main_ws_open_mutex_);
    if (!protocol_) {
        return false;
    }
    if (protocol_->IsAudioChannelOpened()) {
        return true;
    }
    // Sole call site for protocol_->OpenAudioChannel in Application.
    return protocol_->OpenAudioChannel();
}

void Application::LogMainWsOpenEvent(
    const char* event, const main_ws_open::WorkerSnapshot& snap,
    const char* result) const {
    ESP_LOGI(TAG,
             "[MAIN_WS_OPEN] event=%s request_id=%u source=%s "
             "require_presence=%d presence_generation=%u result=%s",
             event, static_cast<unsigned>(snap.request_id),
             main_ws_open::SourceName(snap.source),
             snap.require_presence ? 1 : 0,
             static_cast<unsigned>(snap.presence_generation),
             result != nullptr ? result : "-");
    test_observability::Event("proactive_ws", event,
                              snap.presence_generation,
                              result != nullptr ? result : "-",
                              main_ws_open::SourceName(snap.source),
                              static_cast<int>(snap.request_id));
}

void Application::ClearPendingMainWsActionLocked() {
    std::lock_guard<std::mutex> lock(main_ws_request_mutex_);
    const bool had_proactive =
        pending_main_ws_action_ == PendingMainWsAction::kInjectChatText &&
        ProactiveWakeCoordinator::IsProactiveGreetingPayload(pending_chat_text_);
    pending_main_ws_action_ = PendingMainWsAction::kNone;
    pending_chat_text_.clear();
    pending_wake_word_.clear();
    pending_wake_word_from_audio_ = false;
    if (had_proactive) {
        ProactiveWakeCoordinator::GetInstance().DiscardPendingGreeting(
            "pending_cleared");
    }
}

bool Application::EnsureMainAudioChannelOpen() {
    if (!protocol_) return false;
    if (protocol_->IsAudioChannelOpened()) return true;
    RequestMainAudioChannelOpenAsync(main_ws_open::Source::kReminder,
                                   /*require_presence=*/true);
    return protocol_->IsAudioChannelOpened();
}

void Application::CompleteWakeWordFlow(const std::string& wake_word) {
    if (!protocol_ || !protocol_->IsAudioChannelOpened()) {
        ESP_LOGW(TAG, "CompleteWakeWordFlow channel closed; re-arming open");
        QueueWakeWordChannelOpen();
        return;
    }
    ESP_LOGI(TAG, "Wake word detected: %s", wake_word.c_str());
#if CONFIG_USE_AFE_WAKE_WORD || CONFIG_USE_CUSTOM_WAKE_WORD
    int sent_frames = 0;
    while (auto packet = audio_service_.PopWakeWordPacket()) {
        if (!protocol_->SendAudio(std::move(packet))) {
            ESP_LOGW(TAG, "[WS_AUDIO] wake_preroll_send_failed sent_frames=%d",
                     sent_frames);
            RecoverFromFailedChannelOpen("wake_preroll_send_failed");
            return;
        }
        sent_frames++;
    }
    protocol_->SendWakeWordDetected(wake_word);
    listening_reason_ = kListeningReasonWakeWord;
    SetListeningMode(aec_mode_ == kAecOff ? kListeningModeAutoStop
                                          : kListeningModeRealtime);
#else
    listening_reason_ = kListeningReasonWakeWord;
    SetListeningMode(aec_mode_ == kAecOff ? kListeningModeAutoStop
                                          : kListeningModeRealtime);
    audio_service_.PlaySound(Lang::Sounds::OGG_POPUP);
#endif
}

void Application::CompletePendingMainWsAction(uint32_t ws_open_request_id) {
    PendingMainWsAction action = PendingMainWsAction::kNone;
    std::string chat_text;
    std::string wake_word;
    bool wake_from_audio = false;
    {
        std::lock_guard<std::mutex> lock(main_ws_request_mutex_);
        action = pending_main_ws_action_;
        pending_main_ws_action_ = PendingMainWsAction::kNone;
        chat_text = std::move(pending_chat_text_);
        wake_word = std::move(pending_wake_word_);
        wake_from_audio = pending_wake_word_from_audio_;
        pending_wake_word_from_audio_ = false;
    }
    if (action == PendingMainWsAction::kNone) {
        return;
    }
    if (!protocol_ || !protocol_->IsAudioChannelOpened()) {
        if (action == PendingMainWsAction::kWakeWordFlow) {
            ESP_LOGW(TAG, "pending wake deferred, channel closed; re-arming open");
            QueueWakeWordChannelOpen();
            return;
        }
        ESP_LOGW(TAG, "pending action dropped, channel closed");
        RecoverWakeWordDetection("pending_action_channel_closed");
        if (device_state_ == kDeviceStateConnecting) {
            SetDeviceState(kDeviceStateIdle);
        }
        ProactiveWakeCoordinator::GetInstance().CancelActiveFlow(
            "pending_action_channel_closed");
        return;
    }
    switch (action) {
        case PendingMainWsAction::kToggleChatListening:
            if (listening_reason_ == kListeningReasonUnknown) {
                listening_reason_ = kListeningReasonSystem;
            }
            SetListeningMode(aec_mode_ == kAecOff ? kListeningModeAutoStop
                                                  : kListeningModeRealtime);
            break;
        case PendingMainWsAction::kStartManualListening:
            if (listening_reason_ == kListeningReasonUnknown) {
                listening_reason_ = kListeningReasonSystem;
            }
            SetListeningMode(kListeningModeManualStop);
            break;
        case PendingMainWsAction::kInjectChatText: {
            const std::string& text = chat_text;
            if (text.empty()) break;
            SetDeviceState(kDeviceStateIdle);
            cJSON* root = cJSON_CreateObject();
            cJSON_AddStringToObject(root, "session_id",
                                    protocol_->session_id().c_str());
            cJSON_AddStringToObject(root, "type", "listen");
            cJSON_AddStringToObject(root, "state", "detect");
            cJSON_AddStringToObject(root, "text", text.c_str());
            char* json_str = cJSON_PrintUnformatted(root);
            if (json_str != nullptr) {
                protocol_->SendText(json_str);
                cJSON_free(json_str);
            }
            cJSON_Delete(root);
            ESP_LOGI(TAG, "StartChatWithText injected(async): len=%u",
                     static_cast<unsigned>(text.size()));
            if (ProactiveWakeCoordinator::IsProactiveGreetingPayload(text)) {
                ProactiveWakeCoordinator::GetInstance().OnProactiveGreetingDelivered(
                    protocol_->session_id(), ws_open_request_id);
            }
            break;
        }
        case PendingMainWsAction::kWakeWordFlow: {
            std::string word = wake_word;
            if (wake_from_audio || word.empty()) {
                word = audio_service_.GetLastWakeWord();
            }
            CompleteWakeWordFlow(word);
            break;
        }
        default:
            break;
    }
}

main_ws_submit::PendingActionKind Application::ToPolicyAction(
    PendingMainWsAction action) {
    switch (action) {
        case PendingMainWsAction::kToggleChatListening:
            return main_ws_submit::PendingActionKind::kToggleChatListening;
        case PendingMainWsAction::kStartManualListening:
            return main_ws_submit::PendingActionKind::kStartManualListening;
        case PendingMainWsAction::kInjectChatText:
            return main_ws_submit::PendingActionKind::kInjectChatText;
        case PendingMainWsAction::kWakeWordFlow:
            return main_ws_submit::PendingActionKind::kWakeWordFlow;
        default:
            return main_ws_submit::PendingActionKind::kNone;
    }
}

main_ws_submit::PendingTier Application::CurrentPendingTierLocked() const {
    if (pending_main_ws_action_ == PendingMainWsAction::kNone) {
        return main_ws_submit::PendingTier::kNone;
    }
    return main_ws_submit::TierForAction(ToPolicyAction(pending_main_ws_action_));
}

void Application::ApplyPendingIntentLocked(const MainWsPendingIntent& intent) {
    pending_main_ws_action_ = intent.action;
    pending_chat_text_ = intent.chat_text;
    pending_wake_word_ = intent.wake_word;
    pending_wake_word_from_audio_ = intent.wake_from_audio;
}

void Application::ClearProactiveChatPendingLocked() {
    if (pending_main_ws_action_ == PendingMainWsAction::kInjectChatText &&
        ProactiveWakeCoordinator::IsProactiveGreetingPayload(pending_chat_text_)) {
        pending_main_ws_action_ = PendingMainWsAction::kNone;
        pending_chat_text_.clear();
        ProactiveWakeCoordinator::GetInstance().DiscardPendingGreeting(
            "manual_priority");
    }
}

Application::MainWsSubmitOutcome Application::SubmitMainWsOpenRequestLocked(
    main_ws_open::Source source, bool require_presence,
    const MainWsPendingIntent& intent) {
    MainWsSubmitOutcome outcome;
    if (!protocol_) {
        outcome.result = MainWsOpenRequestResult::kFailedNoProtocol;
        return outcome;
    }

    if (protocol_->IsAudioChannelOpened()) {
        if (intent.has_intent) {
            const main_ws_submit::PendingTier incoming_tier =
                main_ws_submit::TierForAction(ToPolicyAction(intent.action));
            const main_ws_submit::PendingTier existing_tier =
                CurrentPendingTierLocked();
            bool write = false;
            if (incoming_tier == main_ws_submit::PendingTier::kManual) {
                write = true;
            } else if (existing_tier != main_ws_submit::PendingTier::kManual &&
                       existing_tier == main_ws_submit::PendingTier::kNone) {
                write = true;
            }
            if (write) {
                ApplyPendingIntentLocked(intent);
                outcome.pending_applied = true;
            }
        }
        outcome.result = MainWsOpenRequestResult::kAlreadyOpen;
        outcome.ws_request_id = 0;
        return outcome;
    }

    const uint32_t generation =
        PresenceContext::GetInstance().PresenceGeneration();
    main_ws_open::WorkerSnapshot snapshot;
    const main_ws_open::SubmitResult submit =
        main_ws_open::SubmitRequest(ws_open_arbiter_, source, require_presence,
                                    generation, &snapshot);

    const main_ws_submit::PendingTier incoming_tier =
        intent.has_intent
            ? main_ws_submit::TierForAction(ToPolicyAction(intent.action))
            : main_ws_submit::TierForSource(source, require_presence);
    const main_ws_submit::PendingTier existing_tier = CurrentPendingTierLocked();
    const bool write_pending = main_ws_submit::ShouldWritePending(
        submit, incoming_tier, existing_tier, intent.has_intent);

    if (submit == main_ws_open::SubmitResult::kUpgradedManual) {
        ClearProactiveChatPendingLocked();
        ProactiveWakeCoordinator::GetInstance().DiscardPendingGreeting(
            "manual_priority");
    }

    if (write_pending) {
        ApplyPendingIntentLocked(intent);
        outcome.pending_applied = true;
    }

    switch (submit) {
        case main_ws_open::SubmitResult::kStarted:
            outcome.result = MainWsOpenRequestResult::kStarted;
            outcome.ws_request_id = snapshot.request_id;
            break;
        case main_ws_open::SubmitResult::kJoinInflight:
            outcome.result = MainWsOpenRequestResult::kJoined;
            outcome.ws_request_id = main_ws_open::GetActiveRequestId(ws_open_arbiter_);
            break;
        case main_ws_open::SubmitResult::kUpgradedManual:
            outcome.result = MainWsOpenRequestResult::kUpgradedManual;
            outcome.ws_request_id = main_ws_open::GetActiveRequestId(ws_open_arbiter_);
            break;
        case main_ws_open::SubmitResult::kRejectedLowerPriority:
            outcome.result = MainWsOpenRequestResult::kRejectedLowerPriority;
            outcome.ws_request_id = main_ws_open::GetActiveRequestId(ws_open_arbiter_);
            break;
        default:
            outcome.result = MainWsOpenRequestResult::kFailedNoProtocol;
            break;
    }

    return outcome;
}

Application::MainWsSubmitOutcome Application::SubmitMainWsOpenRequest(
    main_ws_open::Source source, bool require_presence,
    const MainWsPendingIntent& intent) {
    if (!protocol_) {
        return {MainWsOpenRequestResult::kFailedNoProtocol, false, 0};
    }

    if (protocol_->IsAudioChannelOpened()) {
        MainWsSubmitOutcome outcome;
        {
            std::lock_guard<std::mutex> lock(main_ws_request_mutex_);
            outcome = SubmitMainWsOpenRequestLocked(source, require_presence, intent);
        }
        if (outcome.pending_applied) {
            CompletePendingMainWsAction(0);
        }
        ProactiveWakeCoordinator::GetInstance().OnAudioChannelReady(
            protocol_->session_id());
        return outcome;
    }

    const uint32_t generation =
        PresenceContext::GetInstance().PresenceGeneration();
    MainWsSubmitOutcome outcome;
    main_ws_open::WorkerSnapshot snapshot{};
    bool start_worker = false;

    {
        std::lock_guard<std::mutex> lock(main_ws_request_mutex_);
        outcome =
            SubmitMainWsOpenRequestLocked(source, require_presence, intent);

        main_ws_open::WorkerSnapshot log_snap{};
        switch (outcome.result) {
            case MainWsOpenRequestResult::kJoined: {
                log_snap.request_id = 0;
                log_snap.source = source;
                log_snap.require_presence = require_presence;
                log_snap.presence_generation = generation;
                LogMainWsOpenEvent("join", log_snap, "inflight");
                break;
            }
            case MainWsOpenRequestResult::kRejectedLowerPriority: {
                log_snap.source = source;
                log_snap.require_presence = require_presence;
                log_snap.presence_generation = generation;
                log_snap.request_id = outcome.ws_request_id;
                LogMainWsOpenEvent("join", log_snap, "rejected_manual_inflight");
                break;
            }
            case MainWsOpenRequestResult::kUpgradedManual: {
                main_ws_open::WorkerSnapshot up_snap{};
                up_snap.request_id = outcome.ws_request_id;
                up_snap.source = source;
                up_snap.require_presence = false;
                up_snap.presence_generation = generation;
                LogMainWsOpenEvent("upgrade_manual", up_snap, "manual_priority");
                break;
            }
            case MainWsOpenRequestResult::kStarted: {
                snapshot.request_id = outcome.ws_request_id;
                snapshot.presence_generation = generation;
                snapshot.require_presence = require_presence;
                snapshot.source = source;
                LogMainWsOpenEvent("request", snapshot, "started");
                start_worker = true;
                break;
            }
            default:
                break;
        }
    }

    if (start_worker) {
        auto* args = new MainWsOpenTaskArgs{this, snapshot};
        if (xTaskCreate(&Application::MainWsOpenTask, "main_ws_open", 4096, args, 5,
                        nullptr) != pdPASS) {
            LogMainWsOpenEvent("open_done", snapshot, "task_create_failed");
            main_ws_open::ClearInflight(ws_open_arbiter_, snapshot.request_id);
            delete args;
            RecoverFromFailedChannelOpen("task_create_failed");
            outcome.result = MainWsOpenRequestResult::kFailedNoProtocol;
            outcome.pending_applied = false;
        }
    }

    return outcome;
}

Application::MainWsOpenRequestResult Application::RequestMainAudioChannelOpenAsync(
    main_ws_open::Source source, bool require_presence) {
    return SubmitMainWsOpenRequest(source, require_presence,
                                   MainWsPendingIntent::None())
        .result;
}

void Application::HandleMainWsOpenComplete(main_ws_open::WorkerSnapshot snapshot,
                                           bool ok) {
    const bool radar_present =
        PresenceContext::GetInstance().IsRadarPresent();
    const uint32_t current_generation =
        PresenceContext::GetInstance().PresenceGeneration();

    auto peek_pending = [this]() {
        std::lock_guard<std::mutex> lock(main_ws_request_mutex_);
        return pending_main_ws_action_;
    };
    const bool channel_open =
        protocol_ && protocol_->IsAudioChannelOpened();

    if (main_ws_open::IsStaleRequest(ws_open_arbiter_, snapshot.request_id)) {
        LogMainWsOpenEvent("discard_stale", snapshot, "stale_request_id");
        ProactiveWakeCoordinator::GetInstance().DiscardPendingGreeting(
            "stale_ws_request", snapshot.request_id);
        const PendingMainWsAction pending = peek_pending();
        if (pending == PendingMainWsAction::kWakeWordFlow && channel_open) {
            ESP_LOGI(TAG, "discard_stale keeping wake flow, channel open");
            CompletePendingMainWsAction(snapshot.request_id);
            return;
        }
        if (main_ws_open::IsInflight(ws_open_arbiter_)) {
            ESP_LOGW(TAG, "discard_stale superseded, inflight continues");
            return;
        }
        if (device_state_ == kDeviceStateConnecting ||
            pending == PendingMainWsAction::kWakeWordFlow) {
            RecoverFromFailedChannelOpen("discard_stale");
        } else {
            ESP_LOGW(TAG, "discard_stale ignored state=%s",
                     DeviceStateName(device_state_));
        }
        return;
    }

    if (!ok) {
        LogMainWsOpenEvent("open_done", snapshot, "open_failed");
        main_ws_open::ClearInflight(ws_open_arbiter_, snapshot.request_id);
        RecoverFromFailedChannelOpen("open_failed");
        return;
    }

    if (main_ws_open::ShouldDiscardStale(ws_open_arbiter_, snapshot.request_id,
                                         snapshot.presence_generation,
                                         radar_present, current_generation)) {
        LogMainWsOpenEvent("discard_stale", snapshot, "presence_or_generation");
        if (peek_pending() == PendingMainWsAction::kWakeWordFlow &&
            channel_open) {
            main_ws_open::ClearInflight(ws_open_arbiter_, snapshot.request_id);
            ProactiveWakeCoordinator::GetInstance().CancelActiveFlow(
                "manual_wake_priority");
            ESP_LOGI(TAG, "discard_stale keeping wake flow, channel open");
            CompletePendingMainWsAction(snapshot.request_id);
            return;
        }
        if (channel_open) {
            protocol_->CloseAudioChannel();
        }
        main_ws_open::ClearInflight(ws_open_arbiter_, snapshot.request_id);
        RecoverFromFailedChannelOpen("discard_stale");
        return;
    }

    LogMainWsOpenEvent("open_done", snapshot, "ok");
    main_ws_open::ClearInflight(ws_open_arbiter_, snapshot.request_id);
    CompletePendingMainWsAction(snapshot.request_id);
    FlushPendingReminderProtocolMessages();
    ProactiveWakeCoordinator::GetInstance().OnAudioChannelReady(
        GetAudioSessionId());
    Schedule([this]() { FlushPendingReminders(); });
}

uint32_t Application::GetMainWsOpenActiveRequestId() const {
    return main_ws_open::GetActiveRequestId(ws_open_arbiter_);
}

void Application::MainWsOpenTask(void* arg) {
    std::unique_ptr<MainWsOpenTaskArgs> args(
        static_cast<MainWsOpenTaskArgs*>(arg));
    Application* self = args->app;
    const main_ws_open::WorkerSnapshot snapshot = args->snapshot;

    self->LogMainWsOpenEvent("open_start", snapshot, "worker");
    const bool ok = self->OpenMainAudioChannelExclusive();
    self->Schedule([self, snapshot, ok]() {
        self->HandleMainWsOpenComplete(snapshot, ok);
    });
    vTaskDelete(nullptr);
}

bool Application::IsMainAudioChannelOpenInFlight() const {
    return main_ws_open::IsInflight(ws_open_arbiter_);
}

void Application::OnPersonIdentified(const std::string& face_id,
                                     const std::string& base_greeting) {
    // Legacy entry: route verified face into ProactiveWakeCoordinator.
    // display_name preferred from base_greeting when it is a plain name;
    // Stable user IDs must not be exposed in the spoken greeting payload.
    std::string display_name = base_greeting;
    std::string user_id = face_id;
    FaceIdentityBinding server_binding;
    if (IdentityManager::GetInstance().ResolveFaceIdentity(face_id,
                                                           &server_binding)) {
        display_name = server_binding.display_name;
    } else if (PresenceContext::IsStableUserId(face_id)) {
        UserIdentity identity;
        if (IdentityManager::GetInstance().FindByFaceId(face_id, &identity) &&
            !identity.display_name.empty()) {
            display_name = identity.display_name;
        } else if (display_name.empty() ||
                   PresenceContext::IsStableUserId(display_name)) {
            display_name.clear();
        }
    }
    const uint32_t gen = PresenceContext::GetInstance().PresenceGeneration();
    ProactiveWakeCoordinator::GetInstance().OnFaceVerified(
        gen, user_id, display_name);
    (void)base_greeting;
}

bool Application::SetCurrentPresentUserFromFaceProfile(
    const std::string& face_profile_id,
    const std::string& fallback_display_name) {
    FaceIdentityBinding binding;
    if (!IdentityManager::GetInstance().ResolveFaceIdentity(face_profile_id,
                                                             &binding)) {
        // A newly observed unknown/unbound face must also clear a previously
        // reported in-room user on this connection.
        ClearCurrentPresentUserFromFaceProfile();
        ESP_LOGI(TAG,
                 "[IDENTITY] present face is unknown or unbound; server context not set");
        return false;
    }

    UserContext::GetInstance().SetCurrentPresentUser(binding.user_id,
                                                      binding.display_name);
    UserContext::GetInstance().SetActiveUserId(binding.user_id);

    auto publish = [this, profile = binding.face_profile_id,
                    user = binding.user_id]() {
        if (!protocol_ || !protocol_->IsAudioChannelOpened()) {
            ESP_LOGD(TAG, "[IDENTITY] present user not sent: audio channel closed");
            return;
        }
        cJSON* root = cJSON_CreateObject();
        cJSON_AddStringToObject(root, "type", "identity_context");
        cJSON* present = cJSON_CreateObject();
        cJSON_AddStringToObject(present, "user_id", user.c_str());
        cJSON_AddStringToObject(present, "face_profile_id", profile.c_str());
        cJSON_AddItemToObject(root, "current_present_user", present);
        char* serialized = cJSON_PrintUnformatted(root);
        cJSON_Delete(root);
        if (!serialized) return;
        const std::string message(serialized);
        cJSON_free(serialized);
        if (!protocol_->SendText(message)) {
            ESP_LOGW(TAG, "[IDENTITY] failed to send current present user");
        }
    };
    if (xTaskGetCurrentTaskHandle() == main_event_loop_task_handle_) {
        publish();
    } else {
        Schedule(std::move(publish));
    }
    (void)fallback_display_name;  // Server-bound display name is authoritative.
    return true;
}

void Application::ClearCurrentPresentUserFromFaceProfile() {
    UserContext::GetInstance().ClearCurrentPresentUser();
    auto publish = [this]() {
        if (!protocol_ || !protocol_->IsAudioChannelOpened()) return;
        const std::string message =
            "{\"type\":\"identity_context\",\"current_present_user\":null}";
        if (!protocol_->SendText(message)) {
            ESP_LOGW(TAG, "[IDENTITY] failed to clear current present user");
        }
    };
    if (xTaskGetCurrentTaskHandle() == main_event_loop_task_handle_) {
        publish();
    } else {
        Schedule(std::move(publish));
    }
}

void Application::SendMcpMessage(const std::string& payload) {
    if (protocol_ == nullptr) {
        return;
    }

    // Make sure you are using main thread to send MCP message
    if (xTaskGetCurrentTaskHandle() == main_event_loop_task_handle_) {
        protocol_->SendMcpMessage(payload);
    } else {
        Schedule([this, payload = std::move(payload)]() {
            protocol_->SendMcpMessage(payload);
        });
    }
}

std::string Application::GetAudioSessionId() const {
    if (!protocol_) return {};
    return protocol_->session_id();
}

void Application::GetAudioQueueStats(size_t& encode_queue, size_t& send_queue) {
    audio_service_.GetQueueStats(encode_queue, send_queue);
}

void Application::OnAudioSessionClosed(const std::string& closed_session_id) {
    // Invalidate MCP cards / reminder presentation bound to the closed session
    // so a reconnect cannot act on stale UI from the previous session.
    ReminderCoordinator::GetInstance().OnSessionClosed(closed_session_id);
    FaceRoster::GetInstance().OnAudioSessionClosed(closed_session_id);
    Schedule([this, closed_session_id]() {
        MarkReminderInteractionTransportClosed();
        ESP_LOGI(TAG, "[WS_DIAG] session_closed id_len=%u reminder_cards_retained=1",
                 static_cast<unsigned>(closed_session_id.size()));
    });
}

bool Application::IsMainAudioChannelOpened() const {
    return protocol_ != nullptr && protocol_->IsAudioChannelOpened();
}

void Application::SendReminderProtocolMessage(const std::string& payload) {
    if (payload.empty()) return;
    // Presynthesis must not wait for radar presence.  Queue until the
    // primary conversation WebSocket has completed hello.
    auto send = [this, payload]() {
        EnqueueOrSendReminderProtocolMessage(payload);
    };
    if (xTaskGetCurrentTaskHandle() == main_event_loop_task_handle_) {
        send();
    } else {
        Schedule(send);
    }
}

namespace {
constexpr size_t kMaxPendingReminderProtocolMessages = 8;

bool ReminderVoiceRequestKey(const std::string& payload, std::string* key) {
    if (!key) return false;
    cJSON* root = cJSON_Parse(payload.c_str());
    if (!root) return false;
    auto* type = cJSON_GetObjectItem(root, "type");
    auto* instance = cJSON_GetObjectItem(root, "instance_id");
    auto* voice_revision = cJSON_GetObjectItem(root, "voice_revision");
    bool ok = cJSON_IsString(type) && type->valuestring &&
              std::strcmp(type->valuestring, "reminder_voice_request") == 0 &&
              cJSON_IsString(instance) && instance->valuestring &&
              cJSON_IsNumber(voice_revision);
    if (ok) {
        *key = std::string(instance->valuestring) + ":" +
               std::to_string(static_cast<uint32_t>(voice_revision->valuedouble));
    }
    cJSON_Delete(root);
    return ok;
}
}  // namespace

void Application::EnqueueOrSendReminderProtocolMessage(
    const std::string& payload) {
    if (!protocol_) return;
    if (protocol_->IsAudioChannelOpened()) {
        ReminderControlClient::GetInstance().OnMainChannelBecameAvailable();
        ESP_LOGI(TAG,
                 "[REMINDER_DELIVERY] event=voice_request "
                 "transport=existing_ws");
        protocol_->SendText(payload);
        return;
    }

    std::string incoming_key;
    const bool have_key = ReminderVoiceRequestKey(payload, &incoming_key);
    if (have_key) {
        pending_reminder_protocol_messages_.erase(
            std::remove_if(
                pending_reminder_protocol_messages_.begin(),
                pending_reminder_protocol_messages_.end(),
                [&](const std::string& item) {
                    std::string existing_key;
                    return ReminderVoiceRequestKey(item, &existing_key) &&
                           existing_key == incoming_key;
                }),
            pending_reminder_protocol_messages_.end());
    }
    pending_reminder_protocol_messages_.push_back(payload);
    while (pending_reminder_protocol_messages_.size() >
           kMaxPendingReminderProtocolMessages) {
        pending_reminder_protocol_messages_.erase(
            pending_reminder_protocol_messages_.begin());
    }
    ESP_LOGI(TAG,
             "[REMINDER_DELIVERY] event=voice_request "
             "transport=queued pending=%u",
             static_cast<unsigned>(pending_reminder_protocol_messages_.size()));
    RequestMainAudioChannelOpenAsync(main_ws_open::Source::kReminder,
                                     /*require_presence=*/false);
}

void Application::FlushPendingReminderProtocolMessages() {
    if (!protocol_ || !protocol_->IsAudioChannelOpened() ||
        pending_reminder_protocol_messages_.empty()) {
        return;
    }
    ReminderControlClient::GetInstance().OnMainChannelBecameAvailable();
    auto pending = std::move(pending_reminder_protocol_messages_);
    pending_reminder_protocol_messages_.clear();
    ESP_LOGI(TAG,
             "[REMINDER_DELIVERY] event=voice_request transport=flush count=%u",
             static_cast<unsigned>(pending.size()));
    for (const auto& payload : pending) {
        protocol_->SendText(payload);
    }
}

bool Application::IsReminderInteractionActive() const {
    return reminder_interaction_.active;
}

void Application::BeginReminderInteraction(const std::string& instance_id,
                                           uint32_t revision,
                                           time_t expires_at) {
    if (instance_id.empty() || revision == 0 || expires_at <= 0) return;
    auto begin = [this, instance_id, revision, expires_at]() {
        BeginReminderInteractionOnMain(instance_id, revision, expires_at);
    };
    if (xTaskGetCurrentTaskHandle() == main_event_loop_task_handle_) {
        begin();
    } else {
        Schedule(begin);
    }
}

void Application::EndReminderInteraction(const std::string& instance_id,
                                         uint32_t revision,
                                         const char* reason) {
    const std::string safe_reason = reason ? reason : "closed";
    auto end = [this, instance_id, revision, safe_reason]() {
        EndReminderInteractionOnMain(instance_id, revision,
                                    safe_reason.c_str());
    };
    if (xTaskGetCurrentTaskHandle() == main_event_loop_task_handle_) {
        end();
    } else {
        Schedule(end);
    }
}

void Application::RefreshReminderInteraction() {
    auto refresh = [this]() { ActivateReminderInteractionIfReady(); };
    if (xTaskGetCurrentTaskHandle() == main_event_loop_task_handle_) {
        refresh();
    } else {
        Schedule(refresh);
    }
}

void Application::BeginReminderInteractionOnMain(const std::string& instance_id,
                                                 uint32_t revision,
                                                 time_t expires_at) {
    const time_t now = time(nullptr);
    // Keep the device-side contract identical to the service's defensive
    // window.  A caller with a stale clock cannot accidentally open a longer
    // microphone session even before the server applies its own clipping.
    if (now > 0 && expires_at > now + kReminderInteractionMaxSeconds) {
        expires_at = now + kReminderInteractionMaxSeconds;
    }
    if (now > 0 && expires_at <= now) {
        ESP_LOGW(TAG,
                 "[REMINDER_INTERACTION] event=open_ignored "
                 "instance=%s reason=expired",
                 instance_id.c_str());
        return;
    }

    if (reminder_interaction_.active &&
        (reminder_interaction_.instance_id != instance_id ||
         reminder_interaction_.revision != revision)) {
        EndReminderInteractionOnMain(reminder_interaction_.instance_id,
                                    reminder_interaction_.revision,
                                    "preempted");
    }

    const bool same_interaction = reminder_interaction_.active &&
        reminder_interaction_.instance_id == instance_id &&
        reminder_interaction_.revision == revision;
    reminder_interaction_.instance_id = instance_id;
    reminder_interaction_.revision = revision;
    reminder_interaction_.expires_at = expires_at;
    reminder_interaction_.active = true;
    if (!same_interaction) {
        reminder_interaction_.opened_on_channel = false;
        reminder_interaction_.opened_session_id.clear();
    } else if (reminder_interaction_.opened_on_channel) {
        // A VAD/touch interaction extends the same 180-second reminder
        // window.  Do not open a second server guard; renew the existing
        // one with its new expiry.
        SendReminderInteractionEvent("interaction_renewed", nullptr);
    }
    ESP_LOGI(TAG,
             "[REMINDER_INTERACTION] event=local_open instance=%s rev=%u "
             "expires_at=%ld",
             instance_id.c_str(), static_cast<unsigned>(revision),
             static_cast<long>(expires_at));
    ActivateReminderInteractionIfReady();
}

void Application::EndReminderInteractionOnMain(const std::string& instance_id,
                                               uint32_t revision,
                                               const char* reason) {
    if (!reminder_interaction_.active) return;
    if (!instance_id.empty() &&
        (reminder_interaction_.instance_id != instance_id ||
         (revision != 0 && reminder_interaction_.revision != revision))) {
        ESP_LOGI(TAG,
                 "[REMINDER_INTERACTION] event=close_ignored reason=stale "
                 "instance=%s rev=%u",
                 instance_id.c_str(), static_cast<unsigned>(revision));
        return;
    }

    const std::string closing_id = reminder_interaction_.instance_id;
    const uint32_t closing_revision = reminder_interaction_.revision;
    if (reminder_interaction_.opened_on_channel) {
        SendReminderInteractionEvent("interaction_closed", reason);
    }
    reminder_interaction_ = ReminderInteractionState{};
    last_reminder_window_renewal_tick_ = 0;
    ESP_LOGI(TAG,
             "[REMINDER_INTERACTION] event=local_closed instance=%s rev=%u "
             "reason=%s",
             closing_id.c_str(), static_cast<unsigned>(closing_revision),
             reason ? reason : "closed");

    if (device_state_ == kDeviceStateListening &&
        listening_reason_ == kListeningReasonReminder) {
        audio_service_.EnableVoiceProcessing(false);
        SetDeviceState(kDeviceStateIdle);
    }
}

void Application::ActivateReminderInteractionIfReady() {
    if (!reminder_interaction_.active) return;

    const time_t now = time(nullptr);
    if (now > 0 && reminder_interaction_.expires_at <= now) {
        EndReminderInteractionOnMain("", 0, "timeout");
        return;
    }
    if (!protocol_) return;

    if (!protocol_->IsAudioChannelOpened()) {
        // Never open a microphone channel for an empty room.  The durable
        // card remains locally actionable, and a later presence transition
        // calls RefreshReminderInteraction to retry this path.
        if (PresenceContext::GetInstance().IsRadarPresent()) {
            RequestMainAudioChannelOpenAsync(main_ws_open::Source::kReminder,
                                             /*require_presence=*/true);
        }
        return;
    }

    const std::string current_session_id = protocol_->session_id();
    if (!reminder_interaction_.opened_on_channel ||
        reminder_interaction_.opened_session_id != current_session_id) {
        if (!SendReminderInteractionEvent("interaction_opened", nullptr)) {
            return;
        }
        reminder_interaction_.opened_on_channel = true;
        reminder_interaction_.opened_session_id = current_session_id;
    }

    // The server-side guard must be live even while an existing answer drains;
    // actual microphone listening waits until that local audio is finished.
    // After FinishTtsPlayback clears the stream, Speaking is only a leftover
    // state flag and this path may continue into a single listen start.
    if (device_state_ == kDeviceStateSpeaking &&
        tts_stream_active_.load(std::memory_order_acquire)) {
        return;
    }
    if (FaceEnrollmentManager::GetInstance().IsActive()) {
        ESP_LOGI(TAG,
                 "[REMINDER_INTERACTION] event=listen_deferred "
                 "reason=face_enrollment");
        return;
    }
    if (!PresenceContext::GetInstance().IsRadarPresent()) return;

    const time_t remaining_seconds = reminder_interaction_.expires_at - now;
    if (remaining_seconds <= 0) {
        EndReminderInteractionOnMain("", 0, "timeout");
        return;
    }
    const uint64_t remaining_ms = std::min<uint64_t>(
        static_cast<uint64_t>(remaining_seconds) * 1000ULL,
        static_cast<uint64_t>(kReminderInteractionMaxSeconds) * 1000ULL);

    // Snapshot before overwriting so same-window refreshes stay idempotent.
    const bool already_reminder_listen =
        device_state_ == kDeviceStateListening &&
        listening_reason_ == kListeningReasonReminder &&
        listening_mode_ == kListeningModeManualStop;

    // Decide listen mode / reason / timeout before any protocol start so a
    // single ArmListeningAudio (via SetDeviceState) or one conversion owns
    // the listen start — never SetDeviceState + a second start here.
    listening_reason_ = kListeningReasonReminder;
    listening_mode_ = kListeningModeManualStop;
    listening_timeout_ms_ = static_cast<uint32_t>(remaining_ms);

    if (device_state_ == kDeviceStateListening) {
        // Already in the dedicated reminder listen: refreshing the card
        // window is idempotent — do not re-send start or wipe the upload
        // queue mid-utterance.
        if (already_reminder_listen) {
            listening_start_tick_ = xTaskGetTickCount();
            ESP_LOGI(TAG,
                     "[REMINDER_INTERACTION] event=listen_refresh_idempotent "
                     "instance=%s rev=%u remaining_s=%ld",
                     reminder_interaction_.instance_id.c_str(),
                     static_cast<unsigned>(reminder_interaction_.revision),
                     static_cast<long>(remaining_seconds));
            return;
        }
        // Ordinary conversation listen → reminder listen: one mode update.
        // Do not ResetUploadQueues; in-flight speech must not be discarded.
        listening_start_tick_ = xTaskGetTickCount();
        protocol_->SendStartListening(listening_mode_);
        audio_service_.EnableVoiceProcessing(true);
        audio_service_.EnableWakeWordDetection(false);
        audio_service_.LogUploadStats("listen_start_reminder_convert");
        ESP_LOGI(TAG,
                 "[REMINDER_INTERACTION] event=listen_converted "
                 "instance=%s rev=%u remaining_s=%ld",
                 reminder_interaction_.instance_id.c_str(),
                 static_cast<unsigned>(reminder_interaction_.revision),
                 static_cast<long>(remaining_seconds));
        return;
    }

    SetDeviceState(kDeviceStateListening);
    ESP_LOGI(TAG,
             "[REMINDER_INTERACTION] event=listening instance=%s rev=%u "
             "remaining_s=%ld",
             reminder_interaction_.instance_id.c_str(),
             static_cast<unsigned>(reminder_interaction_.revision),
             static_cast<long>(remaining_seconds));
}

bool Application::SendReminderInteractionEvent(const char* event,
                                                const char* reason) {
    if (!event || !protocol_ || !protocol_->IsAudioChannelOpened() ||
        !reminder_interaction_.active) {
        return false;
    }
    cJSON* root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", "reminder_event");
    cJSON_AddStringToObject(root, "event", event);
    cJSON_AddStringToObject(root, "instance_id",
                            reminder_interaction_.instance_id.c_str());
    cJSON_AddNumberToObject(root, "revision", reminder_interaction_.revision);
    if (strcmp(event, "interaction_opened") == 0 ||
        strcmp(event, "interaction_renewed") == 0) {
        cJSON_AddNumberToObject(root, "expires_at",
                                static_cast<double>(reminder_interaction_.expires_at));
    }
    if (reason && reason[0] != '\0') {
        cJSON_AddStringToObject(root, "reason", reason);
    }
    char* json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!json) return false;
    protocol_->SendText(json);
    cJSON_free(json);
    ESP_LOGI(TAG,
             "[REMINDER_INTERACTION] event=protocol_sent type=%s instance=%s rev=%u",
             event, reminder_interaction_.instance_id.c_str(),
             static_cast<unsigned>(reminder_interaction_.revision));
    return true;
}

void Application::MarkReminderInteractionTransportClosed() {
    if (!reminder_interaction_.active) return;
    reminder_interaction_.opened_on_channel = false;
    reminder_interaction_.opened_session_id.clear();
    ESP_LOGI(TAG,
             "[REMINDER_INTERACTION] event=transport_closed instance=%s",
             reminder_interaction_.instance_id.c_str());
}

void Application::SetAecMode(AecMode mode) {
    aec_mode_ = mode;
    Schedule([this]() {
        auto& board = Board::GetInstance();
        auto display = board.GetDisplay();
        switch (aec_mode_) {
        case kAecOff:
            audio_service_.EnableDeviceAec(false);
            display->ShowNotification(Lang::Strings::RTC_MODE_OFF);
            break;
        case kAecOnServerSide:
            audio_service_.EnableDeviceAec(false);
            display->ShowNotification(Lang::Strings::RTC_MODE_ON);
            break;
        case kAecOnDeviceSide:
            audio_service_.EnableDeviceAec(true);
            display->ShowNotification(Lang::Strings::RTC_MODE_ON);
            break;
        }

        // If the AEC mode is changed, close the audio channel
        if (protocol_ && protocol_->IsAudioChannelOpened()) {
            protocol_->CloseAudioChannel();
        }
    });
}

void Application::PlaySound(const std::string_view& sound) {
    audio_service_.PlaySound(sound);
}

void Application::NotifyUserInteraction(bool is_from_touch) {
    Board::GetInstance().GetDisplay()->RecordDisplayActivity();
    if (device_state_ == kDeviceStateListening && listening_start_tick_ != 0) {
        listening_start_tick_ = xTaskGetTickCount();
        listening_timeout_ms_ = LISTENING_TIMEOUT_MS;
    }
    if (!is_from_touch) {
        awaiting_server_reply_ = true;
    }
    if (IsReminderInteractionActive()) {
        const uint32_t now = xTaskGetTickCount();
        if (last_reminder_window_renewal_tick_ == 0 ||
            now - last_reminder_window_renewal_tick_ >= pdMS_TO_TICKS(1000)) {
            last_reminder_window_renewal_tick_ = now;
            ReminderCoordinator::GetInstance().RenewCurrentCardWindow(time(nullptr));
        }
    }
}

void Application::ResetListeningTimeout(bool is_from_touch) {
    NotifyUserInteraction(is_from_touch);
}

void Application::FlushPendingReminders() {
    ReminderCoordinator::GetInstance().Tick(time(nullptr), true);
}

void Application::BeginTtsStream(uint32_t generation) {
    if (generation != tts_generation_.load(std::memory_order_acquire) ||
        generation == tts_closed_generation_ ||
        FaceEnrollmentManager::GetInstance().IsActive() ||
        (device_state_ != kDeviceStateListening && device_state_ != kDeviceStateSpeaking &&
         device_state_ != kDeviceStateIdle)) {
        ESP_LOGI(TAG, "[TTS_LOCAL] event=start_drop reason=stale_or_ineligible");
        return;
    }
    // A new tts.start is a hard generation boundary even when we were already
    // in Speaking.  SetDeviceState intentionally does not reset on a same
    // state transition, so do it here before any new packet is accepted.
    audio_service_.ResetDecoder();
    active_tts_generation_ = generation;
    pending_subtitle_markers_.clear();
    last_tts_sentence_.clear();
    tts_stream_active_.store(true, std::memory_order_release);
    tts_stop_received_ = false;
    tts_received_audio_ = false;
    tts_stream_started_us_ = esp_timer_get_time();
    tts_last_rx_us_ = tts_stream_started_us_;
    aborted_ = false;
    auto* display = Board::GetInstance().GetDisplay();
    if (display) display->SetChatMessage("assistant", "");
    ESP_LOGI(TAG, "[TTS_LOCAL] event=start decoder_reset=1");
    SetDeviceState(kDeviceStateSpeaking);
}

void Application::HandleIncomingTtsAudio(uint32_t generation, std::unique_ptr<AudioStreamPacket> packet) {
    if (!packet || generation != tts_generation_.load(std::memory_order_acquire) ||
        generation == tts_closed_generation_ ||
        FaceEnrollmentManager::GetInstance().IsActive()) {
        ESP_LOGD(TAG, "[TTS_LOCAL] event=audio_drop reason=stale_or_inactive");
        return;
    }
    // Binary frames can be scheduled before tts.start's callback. Start the
    // stream on the matching generation instead of dropping the whole reply.
    // Frames for a generation that already finished (stop+drain / anomaly)
    // are rejected above via tts_closed_generation_.
    if (!tts_stream_active_.load(std::memory_order_acquire) ||
        active_tts_generation_ != generation ||
        device_state_ != kDeviceStateSpeaking) {
        BeginTtsStream(generation);
    }
    if (!tts_stream_active_.load(std::memory_order_acquire) ||
        active_tts_generation_ != generation ||
        device_state_ != kDeviceStateSpeaking) {
        ESP_LOGD(TAG, "[TTS_LOCAL] event=audio_drop reason=stale_or_inactive");
        return;
    }
    tts_received_audio_ = true;
    tts_last_rx_us_ = esp_timer_get_time();
    audio_service_.PushPacketToDecodeQueue(std::move(packet));
}

void Application::HandleTtsStop(uint32_t generation) {
    if (generation != tts_generation_.load(std::memory_order_acquire) ||
        generation != active_tts_generation_ || !tts_stream_active_ ||
        device_state_ != kDeviceStateSpeaking) return;
    tts_stop_received_ = true;
    UpdateTtsPlayback();
}

void Application::QueueTtsSubtitle(uint32_t generation,
                                   uint64_t playback_sequence,
                                   const std::string& text) {
    if (text.empty()) return;
    if (generation != tts_generation_.load(std::memory_order_acquire)) {
        ESP_LOGI(TAG, "[TTS_LOCAL] event=subtitle_drop reason=stale_generation");
        return;
    }
    if (!tts_stream_active_.load(std::memory_order_acquire) || generation != active_tts_generation_) return;
    pending_subtitle_markers_.push_back({playback_sequence, text});
    ESP_LOGI(TAG,
             "[TTS_LOCAL] event=subtitle_queued target=%lu:%lu bytes=%u",
             static_cast<unsigned long>(playback_sequence >> 32),
             static_cast<unsigned long>(playback_sequence & 0xffffffffULL),
             static_cast<unsigned>(text.size()));
    UpdateTtsPlayback();
}

void Application::UpdateTtsPlayback() {
    if (!tts_stream_active_.load(std::memory_order_acquire) ||
        active_tts_generation_ != tts_generation_.load(std::memory_order_acquire)) return;

    AudioService::DownlinkStats stats;
    audio_service_.GetDownlinkStats(stats);
    while (!pending_subtitle_markers_.empty() &&
           stats.last_played_sequence >=
               pending_subtitle_markers_.front().playback_sequence) {
        last_tts_sentence_ = pending_subtitle_markers_.front().text;
        auto* display = Board::GetInstance().GetDisplay();
        if (display) {
            display->SetChatMessage("assistant", last_tts_sentence_.c_str());
        }
        ESP_LOGI(TAG,
                 "[TTS_LOCAL] event=subtitle_show played=%lu:%lu target=%lu:%lu",
                 static_cast<unsigned long>(stats.last_played_sequence >> 32),
                 static_cast<unsigned long>(stats.last_played_sequence & 0xffffffffULL),
                 static_cast<unsigned long>(pending_subtitle_markers_.front().playback_sequence >> 32),
                 static_cast<unsigned long>(pending_subtitle_markers_.front().playback_sequence & 0xffffffffULL));
        pending_subtitle_markers_.pop_front();
    }

    // Subtitle callbacks only refresh the display; they never end playback.
    // Normal completion requires both a matching tts.stop and local drain.
    // The codec holds the currently output frame outside the queues, and
    // IsPlaybackDrained includes that frame.
    const bool drained = audio_service_.IsPlaybackDrained();
    if (tts_stop_received_) {
        if (!drained) {
            return;
        }
        FinishTtsPlayback("stop_and_drained", /*abnormal=*/false);
        return;
    }

    if (!drained) {
        return;
    }

    // Drained with no tts.stop yet: wait through real streaming gaps using
    // monotonic time since the last RX (or since start if no audio arrived).
    // Active playback (!drained) never reaches this branch. Fresh RX refreshes
    // tts_last_rx_us_ in HandleIncomingTtsAudio, so continuous receive cannot
    // accumulate idle toward kTtsAbnormalIdleTimeoutMs (provisional).
    const int64_t now_us = esp_timer_get_time();
    const int64_t anchor_us =
        tts_received_audio_ ? tts_last_rx_us_ : tts_stream_started_us_;
    if (anchor_us <= 0) {
        return;
    }
    const int64_t idle_ms = (now_us - anchor_us) / 1000;
    if (idle_ms < static_cast<int64_t>(kTtsAbnormalIdleTimeoutMs)) {
        return;
    }

    const char* reason =
        tts_received_audio_ ? "missing_stop_timeout" : "no_audio_timeout";
    ESP_LOGW(TAG,
             "[TTS_LOCAL] event=stream_anomaly reason=%s idle_ms=%lu "
             "timeout_ms=%lu rx=%lu audio=%d",
             reason, static_cast<unsigned long>(std::min<int64_t>(idle_ms, UINT32_MAX)),
             static_cast<unsigned long>(kTtsAbnormalIdleTimeoutMs),
             static_cast<unsigned long>(stats.rx_frames),
             tts_received_audio_ ? 1 : 0);
    FinishTtsPlayback(reason, /*abnormal=*/true);
}

void Application::FinishTtsPlayback(const char* reason, bool abnormal) {
    const uint32_t finished_generation = active_tts_generation_;
    awaiting_server_reply_ = false;
    listening_timeout_ms_ = LISTENING_TIMEOUT_MS;

    // Mark this generation closed before clearing so already-queued late
    // audio cannot resurrect Speaking. Do not bump tts_generation_ here:
    // a concurrent tts.start may already own the next id.
    if (finished_generation != 0) {
        tts_closed_generation_ = finished_generation;
    }
    if (abnormal) {
        // Drop decode/playback residue so a late fragment cannot restart
        // the same (now closed) generation after we leave Speaking.
        audio_service_.ResetDecoder();
    }
    ClearTtsStream(true, false);

    if (FaceEnrollmentManager::GetInstance().IsActive()) {
        ESP_LOGI(TAG, "[TTS_LOCAL] event=finished reason=%s next=hold face_enrollment=1",
                 reason ? reason : "-");
        return;
    }

    // Reminder listen arms at most once below. Ordinary replies fall through
    // to a single SetDeviceState(Listening). Never arm listen twice.
    if (reminder_interaction_.active) {
        ActivateReminderInteractionIfReady();
        if (device_state_ == kDeviceStateSpeaking) {
            // Presence/channel deferred the mic; leave a wakeable idle state
            // instead of staying stuck in Speaking with a silent speaker.
            SetDeviceState(kDeviceStateIdle);
        }
    } else {
        SetDeviceState(kDeviceStateListening);
    }

    // A card that arrived while this stream was speaking deliberately kept
    // its reminder voice deferred.  Release that queue at the actual local
    // playback boundary instead of waiting for Listening to time out.
    const time_t reminder_now = time(nullptr);
    if (reminder_now > 1000000000L) {
        ReminderCoordinator::GetInstance().Tick(reminder_now, true);
    }
    ESP_LOGI(TAG,
             "[TTS_LOCAL] event=finished reason=%s abnormal=%d next_state=%s "
             "timeout_ms=%lu",
             reason ? reason : "-", abnormal ? 1 : 0,
             STATE_STRINGS[device_state_],
             static_cast<unsigned long>(listening_timeout_ms_));
}

void Application::ClearTtsStream(bool clear_subtitle, bool invalidate_pending) {
    if (invalidate_pending) {
        // Advancing the id without a server tts.start leaves a synthetic
        // generation. Mark it closed so binary frames cannot BeginTtsStream
        // on that hole (e.g. after AbortSpeaking / channel close).
        tts_closed_generation_ =
            tts_generation_.fetch_add(1, std::memory_order_acq_rel) + 1;
    }
    active_tts_generation_ = 0;
    pending_subtitle_markers_.clear();
    tts_stream_active_.store(false, std::memory_order_release);
    tts_stop_received_ = false;
    tts_received_audio_ = false;
    tts_stream_started_us_ = 0;
    tts_last_rx_us_ = 0;
    last_tts_sentence_.clear();
    if (clear_subtitle) {
        auto* display = Board::GetInstance().GetDisplay();
        if (display) display->SetChatMessage("assistant", "");
    }
}
