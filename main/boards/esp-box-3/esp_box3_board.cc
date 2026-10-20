#include "display/home_render_config.h"
#include "utils/home_render_options.h"
#include "wifi_board.h"
#include "codecs/box_audio_codec.h"
#include "display/display.h"
#include "display/lcd_display.h"
#include "esp_lcd_st7796.h"
#include "application.h"
#include "reminder_coordinator.h"
#include "button.h"
#include "config.h"
#include "touch/touch_manager.h"
#include "touch/gesture_engine.h"
#include "touch/gesture_handler.h"
#include "presence_sensor.h"
#include "proactive_wake_coordinator.h"
#include "camera_manager.h"
#include "boards/common/esp32_camera.h"
#include "device_state_event.h"
#include "behavior_logger.h"
#include "proactive_manager.h"
#include "user_context.h"
#include "presence_context.h"
#include "identity_client.h"
#include "identity_manager.h"
#include "face_enrollment_manager.h"
#include "task_diagnostics.h"
#ifndef CONFIG_USE_USB_STREAM
#include <esp_video_init.h>
#include <esp_video_device.h>
#endif
#include <esp_timer.h>
#include <esp_spiffs.h>
#include <esp_log.h>
#include <esp_system.h>
#include <esp_heap_caps.h>
#include <esp_lcd_panel_vendor.h>
#include <driver/gpio.h>
#include <driver/i2c_master.h>
#include <driver/spi_common.h>
#include <fcntl.h>
#include <unistd.h>
#include <driver/usb_serial_jtag.h>
#include <wifi_station.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <atomic>
#include <string>
#include <cstdio>

#define TAG "EspBox3Board"

// USB Serial/JTAG and OTG Host share the S3 internal PHY. Select its owner
// once per boot, after the physical switch has been moved to the desired port.
#if defined(CONFIG_USE_USB_STREAM) || defined(CONFIG_ESP_VIDEO_ENABLE_USB_UVC_VIDEO_DEVICE)
static bool UsbConsoleConnectedAtBoot() {
    // The IDF connection monitor starts optimistic; wait for real SOF samples.
    vTaskDelay(pdMS_TO_TICKS(100));
    const int64_t deadline = esp_timer_get_time() + 3000000;
    int connected_samples = 0;
    while (esp_timer_get_time() < deadline) {
        if (usb_serial_jtag_is_connected()) {
            if (++connected_samples >= 3) return true;
        } else {
            connected_samples = 0;
        }
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    return false;
}
#endif

#ifdef CONFIG_USE_USB_STREAM
static void NormalizeUsbRuntimePriorities() {
    struct TaskPriority {
        const char* name;
        UBaseType_t priority;
    };
    static constexpr TaskPriority kRuntimePriorities[] = {
        {"usb_proc", 10},
        {"usb_stream_proc", 9},
        {"sample_proc", 8},
    };

    for (const auto& task : kRuntimePriorities) {
        TaskHandle_t handle = xTaskGetHandle(task.name);
        if (handle != nullptr && uxTaskPriorityGet(handle) != task.priority) {
            vTaskPrioritySet(handle, task.priority);
            ESP_LOGI(TAG, "USB runtime priority normalized: task=%s priority=%u",
                     task.name, static_cast<unsigned>(task.priority));
        }
    }
}

static void LogUsbWorkerTask(const char* name) {
    TaskHandle_t handle = xTaskGetHandle(name);
    ESP_LOGI(TAG, "USB_DIAG task=%s handle=%p priority=%u",
             name, handle,
             handle ? static_cast<unsigned>(uxTaskPriorityGet(handle)) : 0U);
}
#endif

// ST7796U init sequence — from YX40018ACT official document (2021-1227-V02)
// esp_lcd_panel_init() sends 0x11(Sleep Out) + 0x36(MADCTL) + 0x3A(COLMOD) automatically;
// 0x36 here overrides that driver default. 0x2A/0x2B/0x2C are handled by draw_bitmap.
static const st7796_lcd_init_cmd_t st7796_init_cmds[] = {
    // NOP + delay: ensure chip is fully awake after driver's auto Sleep Out
    {0x00, (uint8_t []){ 0x00 }, 0, 50},

    // Memory Access Control — this is the register that actually rotates the panel.
    // Previous value 0x48 = MX=1, MY=0, MV=0, BGR=1.
    // 0x88 = MX=0, MY=1, MV=0, BGR=1: another 180° from that orientation.
    // Must match DISPLAY_MIRROR_X/Y + DISPLAY_SWAP_XY in config.h.
    {0x36, (uint8_t []){ 0x88 }, 1, 0},

    // Pixel Format — 16bit RGB565
    {0x3A, (uint8_t []){ 0x55 }, 1, 0},

    // Command Set Enable
    {0xF0, (uint8_t []){ 0xC3 }, 1, 0},
    {0xF0, (uint8_t []){ 0x96 }, 1, 0},

    // Blanking Porch Control
    {0xB4, (uint8_t []){ 0x01 }, 1, 0},

    // Display Function Control
    // Many ST7796 320x320 modules are cropped from a 320x480 GRAM; use 480-line timing.
    {0xB6, (uint8_t []){ 0x80, 0x00, 0x3B }, 3, 0},

    // EM Level
    {0xB7, (uint8_t []){ 0xC6 }, 1, 0},

    // Adjustment Control 3
    {0xE8, (uint8_t []){ 0x40, 0x84, 0x1D, 0x21, 0x28, 0x13, 0x3F, 0x33 }, 8, 0},

    // Power Control 1
    {0xC0, (uint8_t []){ 0xA0, 0x07 }, 2, 0},

    // Power Control 2
    {0xC1, (uint8_t []){ 0x13 }, 1, 0},

    // Power Control 3
    {0xC2, (uint8_t []){ 0xA7 }, 1, 0},

    // VCOM Control
    {0xC5, (uint8_t []){ 0x09 }, 1, 0},

    // Positive Gamma
    {0xE0, (uint8_t []){ 0xF0, 0x17, 0x1B, 0x0B, 0x0A, 0x08, 0x37, 0x44, 0x4B, 0x3C, 0x17, 0x16, 0x2E, 0x35 }, 14, 0},

    // Negative Gamma
    {0xE1, (uint8_t []){ 0xF0, 0x1A, 0x1D, 0x08, 0x06, 0x10, 0x37, 0x33, 0x4A, 0x32, 0x10, 0x11, 0x29, 0x31 }, 14, 0},

    // Command Set Disable
    {0xF0, (uint8_t []){ 0x3C }, 1, 0},
    {0xF0, (uint8_t []){ 0x69 }, 1, 0},

    // Tearing Effect Line ON
    {0x35, (uint8_t []){ 0x00 }, 1, 0},

    // Display Inversion ON
    {0x21, (uint8_t []){ 0x00 }, 0, 0},

    // Sleep Out (official sequence: 0x21 -> 0x11 + 120ms -> 0x29)
    {0x11, (uint8_t []){ 0x00 }, 0, 120},

    // Rewrite MADCTL after Sleep Out so orientation survives 0x11.
    {0x36, (uint8_t []){ 0x88 }, 1, 0},

    // Display ON
    {0x29, (uint8_t []){ 0x00 }, 0, 0},
};

class EspBox3Board : public WifiBoard {
private:
    i2c_master_bus_handle_t i2c_bus_;
    Button boot_button_;
    Display* display_;
    touch::TouchManager touch_manager_;
    touch::GestureEngine gesture_engine_;
    touch::GestureHandler gesture_handler_;
    esp_timer_handle_t gesture_timer_ = nullptr;

    // 鈹€鈹€ 浜轰綋鎰熺煡 + 鎽勫儚澶翠富鍔ㄥ敜閱?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    PresenceSensor* presence_sensor_ = nullptr;
    uint32_t capture_presence_generation_ = 0;
    std::atomic<bool> capture_abort_flag_{false};
    TaskHandle_t capture_task_handle_ = nullptr;
    esp_timer_handle_t zombie_timer_ = nullptr;   // 20s 鍍靛案闃插尽瀹氭椂鍣?
    // 鍍靛案瀹氭椂鍣ㄥ洖璋冿細璁剧疆 abort_flag锛岃 CaptureTask 鑷閫€鍑?    static void ZombieTimerCb(void* arg) {
    static void ZombieTimerCb(void* arg) {
        auto* self = static_cast<EspBox3Board*>(arg);
        ESP_LOGW(TAG, "Zombie timer fired: setting abort_flag");
        self->capture_abort_flag_ = true;
        // 涓嶅己鏉€ Task锛岃 Task 鑷繁妫€鏌?abort_flag 鍚?cleanup
    }

    void InitializePresenceSensor() {
        ESP_LOGI(TAG, "InitializePresenceSensor: creating zombie timer...");
        // 鍒涘缓鍍靛案瀹氭椂鍣?        esp_timer_create_args_t targs = {};
        esp_timer_create_args_t targs = {};
        targs.callback        = ZombieTimerCb;
        targs.arg             = this;
        targs.dispatch_method = ESP_TIMER_TASK;
        targs.name            = "zombie_timer";
        esp_err_t ret = esp_timer_create(&targs, &zombie_timer_);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "esp_timer_create failed: %s", esp_err_to_name(ret));
            return;
        }

        ESP_LOGI(TAG, "InitializePresenceSensor: creating PresenceSensor...");
        presence_sensor_ = new PresenceSensor(
            [this](uint32_t generation) {
                ESP_LOGD(TAG, "Stable presence gen=%u -> Schedule",
                         static_cast<unsigned>(generation));
                auto& app = Application::GetInstance();
                auto display = Board::GetInstance().GetDisplay();
                if (display) display->SetEmotion("neutral");
                app.Schedule([generation]() {
                    ProactiveWakeCoordinator::GetInstance().OnStablePresence(
                        generation);
                });
            },
            [this](uint32_t generation) {
                ProactiveManager::GetInstance().SetSensorAbsentSince(time(nullptr));
                UserContext::GetInstance().ClearPresenceFace();
                UserContext::GetInstance().ClearActiveUserId();
                Application::GetInstance().ClearCurrentPresentUserFromFaceProfile();
                auto display = Board::GetInstance().GetDisplay();
                if (display) display->SetEmotion("sleepy");
                Application::GetInstance().Schedule([generation]() {
                    ProactiveWakeCoordinator::GetInstance().OnStableAbsence(
                        generation);
                });
            }
        );

        ProactiveWakeCoordinator::GetInstance().SetFaceCaptureHandlers(
            [this](uint32_t generation) {
                Application::GetInstance().Schedule([this, generation]() {
                    OnPresenceDetected(generation);
                });
            },
            [this]() {
                capture_abort_flag_ = true;
            });

        ESP_LOGI(TAG, "InitializePresenceSensor: done");

        // First Idle entry: re-run stable dwell check (do not GPIO→OnPresenceDetected).
        DeviceStateEventManager::GetInstance().RegisterStateChangeCallback(
            [this](DeviceState prev, DeviceState curr) {
                if (curr == kDeviceStateIdle && prev != kDeviceStateIdle
                    && prev != kDeviceStateSpeaking
                    && prev != kDeviceStateListening) {
                    {
                        size_t free_c  = heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA);
                        size_t block_c = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA);
                        ESP_LOGD(TAG, "Idle memory: free=%u, largest_block=%u",
                                 (unsigned)free_c, (unsigned)block_c);
                    }
                    if (presence_sensor_ && !presence_sensor_->IsCooldownActive()) {
                        ESP_LOGI(TAG, "Idle entered: RequestStableRecheck");
                        presence_sensor_->RequestStableRecheck();
                    }
                }
            });
    }

    // Main thread: start CaptureTask for known_one_or_more face verification.
    void OnPresenceDetected(uint32_t presence_generation = 0) {
        auto& app = Application::GetInstance();
        auto& cam_mgr = CameraManager::GetInstance();

        // Enrollment owns CaptureTask exclusivity. Reminder presence still gets
        // OnPresenceChanged(true/false) from the sensor callbacks above.
        if (FaceEnrollmentManager::GetInstance().IsActive()) {
            ESP_LOGI(TAG,
                     "Presence capture skipped: face enrollment is active");
            return;
        }

        // A user-controlled live preview owns the camera until it is closed.
        // Presence detection must not consume its cooldown or alter the UI in
        // that state; a later sensor edge can initiate the proactive flow.
        if (cam_mgr.IsPreviewActive()) {
            ESP_LOGI(TAG, "Presence ignored: user camera preview is active");
            return;
        }

        // Camera consumers never participate in UVC startup. The dedicated
        // usb_cam_init task is the only owner allowed to enumerate/retry.
        if (!cam_mgr.IsStreamReady()) {
            ESP_LOGI(TAG, "Presence deferred: UVC stream is not ready (state=%d)",
                     static_cast<int>(cam_mgr.GetStreamState()));
            return;
        }

        auto state = app.GetDeviceState();
        ESP_LOGI(TAG, "OnPresenceDetected called, state=%d", (int)state);
        ESP_LOGD(TAG, "OnPresenceDetected state=%d", (int)state);

        // 鐧藉悕鍗曪細鍙湁绌洪棽鐘舵€佸厑璁歌Е鍙戞憚鍍忓ご
        // Starting/Connecting 鏃?WiFi 姝ｅ湪杩炴帴锛孶SB 鏋氫妇浼氬拰 WiFi RF 鍐茬獊瀵艰嚧澶辫触
        if (state != kDeviceStateIdle) {
            ESP_LOGI(TAG, "Presence ignored: device state=%d (waiting for idle)", (int)state);
            ESP_LOGD(TAG, "IGNORED state=%d", (int)state);
            return;
        }

        // 寮€鏈哄悗 10 绉掑唴涓嶅搷搴旓紙绛?WiFi 绋冲畾銆佸唴瀛橀噴鏀撅級
        if (esp_timer_get_time() < 10 * 1000 * 1000LL) {
            ESP_LOGI(TAG, "Presence ignored: boot grace period");
            ESP_LOGD(TAG, "IGNORED boot grace");
            return;
        }
        if (presence_sensor_->IsCooldownActive()) {
            ESP_LOGI(TAG, "Presence ignored: cooldown active");
            ESP_LOGD(TAG, "IGNORED cooldown");
            return;
        }

        // 璁剧疆 Cooldown锛?0s 鑷姩瑙ｉ櫎锛屾垨瀵硅瘽缁撴潫鏃舵彁鍓嶈В闄わ級
        capture_presence_generation_ = presence_generation
            ? presence_generation
            : (presence_sensor_ ? presence_sensor_->PresenceGeneration()
                               : PresenceContext::GetInstance().PresenceGeneration());
        presence_sensor_->SetCooldown();
        capture_abort_flag_ = false;

        // 鍚姩鍍靛案瀹氭椂鍣紙20s 鍚庤嫢浠嶆湭杩涘叆瀵硅瘽锛屽己鍒惰В閿侊級
        esp_timer_stop(zombie_timer_);
        esp_timer_start_once(zombie_timer_, 20ULL * 1000 * 1000);

        ESP_LOGI(TAG, "[CAMERA] Presence sensor confirmed a person; requesting one photo for face comparison");
        ESP_LOGD(TAG, "CaptureTask launching");

        auto* display = GetDisplay();
        if (display && !display->IsStandbyClockActive()) display->SetEmotion("thinking");

        xTaskCreate(CaptureTaskEntry, "capture_task", 8192, this, 4, &capture_task_handle_);
        task_diag::LogTaskHandle(TAG, "capture_task_created", capture_task_handle_, 4, -1);
    }

    // CaptureTask 鍏ュ彛锛堥潤鎬侊紝杞彂鍒版垚鍛樺嚱鏁帮級
    static void CaptureTaskEntry(void* arg) {
        static_cast<EspBox3Board*>(arg)->CaptureTaskLoop();
    }

    void CaptureTaskLoop() {
        task_diag::LogCurrentTask(TAG, "capture_task_start", 4, -1);
        auto& app     = Application::GetInstance();
        auto* display = GetDisplay();
        auto& cam_mgr = CameraManager::GetInstance();

        // 鈹€鈹€ 鐘舵€佹満瀹氫箟 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        // ACQUIRING  鈫?姝ｅ湪涓婄數/鏋氫妇/鍒濆鍖栨憚鍍忓ご
        // CAPTURING  鈫?姝ｅ湪鎶撳抚
        // EXPLAINING 鈫?姝ｅ湪涓婁紶鍥剧墖缁欏妯℃€佸ぇ妯″瀷
        // GREETING   鈫?璇嗗埆鎴愬姛锛屽噯澶囪Е鍙戞墦鎷涘懠
        // DONE / FAIL_HW / FAIL_NET / ABORTED 鈫?缁堟€?        enum class CaptureState {
        enum class CaptureState {
            ACQUIRING, CAPTURING, EXPLAINING, GREETING,
            DONE, FAIL_HW, FAIL_NET, ABORTED
        };

        // 杩借釜鏄惁宸叉垚鍔?acquire锛堝喅瀹氱粓鎬佹椂鏄惁闇€瑕?Release锛?        bool camera_acquired = false;
        bool camera_acquired = false;

        CaptureState state = CaptureState::ACQUIRING;
        std::string greeting;
        std::string resolved_face_id;
        std::string first_known_user_id;
        std::string first_known_display_name;

        while (true) {
            // 鍏ㄥ眬涓妫€鏌ワ紙姣忎釜鐘舵€佸叆鍙ｉ兘妫€鏌ワ級
            if (capture_abort_flag_ && state != CaptureState::DONE
                                    && state != CaptureState::FAIL_HW
                                    && state != CaptureState::FAIL_NET
                                    && state != CaptureState::ABORTED) {
                state = CaptureState::ABORTED;
            }

            switch (state) {

            // 鈹€鈹€ ACQUIRING锛氫笂鐢?+ 鏋氫妇 + 鍒濆鍖栨憚鍍忓ご 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
            case CaptureState::ACQUIRING:
                ESP_LOGD(TAG, "CaptureTask: ACQUIRING");
                if (display) {
                    app.Schedule([display]() {
                        if (!display->IsStandbyClockActive()) display->SetEmotion("thinking");
                    });
                }
                if (!cam_mgr.AcquireWithRetry(2, /*background=*/true)) {
                    ESP_LOGW(TAG, "CaptureTask: camera acquire failed (busy or hardware)");
                    ESP_LOGD(TAG, "CaptureTask: acquire failed");
                    // mutex 琚崰 鈫?涓嶆槸纭欢鏁呴殰锛屼笉寤堕暱 cooldown
                    state = CaptureState::FAIL_HW;
                } else {
                    camera_acquired = true;
                    state = CaptureState::CAPTURING;
                }
                break;

            // 鈹€鈹€ CAPTURING锛氭姄甯?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
            case CaptureState::CAPTURING:
                ESP_LOGD(TAG, "CaptureTask: CAPTURING");
                if (!cam_mgr.GetCamera()->Capture()) {
                    ESP_LOGE(TAG, "CaptureTask: Capture() failed (hardware)");
                    ESP_LOGD(TAG, "CaptureTask: Capture failed");
                    state = CaptureState::FAIL_HW;
                } else {
                    state = CaptureState::EXPLAINING;
                }
                break;

            // 鈹€鈹€ EXPLAINING锛氬厛璋冪敤浜鸿劯璇嗗埆 API锛屽啀鏋勯€犵簿鍑?prompt 鍙戠粰澶фā鍨?鈹€鈹€
            case CaptureState::EXPLAINING: {
                ESP_LOGD(TAG, "CaptureTask: EXPLAINING");

                // Step 1: identify via MCP identity_url using a stable user ID.
                auto* esp_cam = static_cast<Esp32Camera*>(cam_mgr.GetCamera());
                IdentityResult face =
                    esp_cam->IdentifyFace(esp_cam->GetLastJpeg());

                ESP_LOGI(TAG,
                         "CaptureTask: face_status=%s user=%s display=%s",
                         face.status.c_str(),
                         face.user_id.empty() ? "-" : face.user_id.c_str(),
                         face.display_name.empty() ? "-"
                                                   : face.display_name.c_str());

                // Greeting requires two consecutive matching known-user results.
                if (!face.IsKnownPerson()) {
                    ESP_LOGI(TAG,
                             "CaptureTask: no confirmed known user; stay silent");
                    state = CaptureState::ABORTED;
                    break;
                }
                if (first_known_user_id.empty()) {
                    first_known_user_id = face.user_id;
                    first_known_display_name = face.display_name;
                    ESP_LOGI(TAG,
                             "CaptureTask: first known user=%s; confirming next frame",
                             first_known_user_id.c_str());
                    state = CaptureState::CAPTURING;
                    break;
                }
                if (face.user_id != first_known_user_id) {
                    ESP_LOGW(TAG,
                             "CaptureTask: user confirmation mismatch: %s vs %s; stay silent",
                             first_known_user_id.c_str(), face.user_id.c_str());
                    state = CaptureState::ABORTED;
                    break;
                }

                const std::string display_name =
                    !face.display_name.empty() ? face.display_name
                    : !first_known_display_name.empty()
                          ? first_known_display_name
                          : face.user_id;
                resolved_face_id =
                    ProactiveManager::GetInstance().ResolveFaceId(display_name);

                UserContext::GetInstance().SetPresenceFace(display_name);
                const bool is_bound_user =
                    app.SetCurrentPresentUserFromFaceProfile(
                        face.user_id, display_name);
                const std::string present_user_id = is_bound_user
                    ? UserContext::GetInstance().GetCurrentPresentUserId()
                    : face.user_id;
                const std::string present_display_name = is_bound_user
                    ? UserContext::GetInstance().GetCurrentPresentDisplayName()
                    : display_name;
                PresenceContext::GetInstance().SetConfirmedIdentity(
                    present_user_id, present_display_name,
                    face.confidence, face.status,
                    PresenceContext::GetInstance().PresenceGeneration());

                auto* disp = Board::GetInstance().GetDisplay();
                if (disp) {
                    auto* lcd = dynamic_cast<LcdDisplay*>(disp);
                    if (lcd) lcd->InvalidateHomeContext();
                    app.Schedule([disp]() { disp->UpdateStatusBar(); });
                }

                // Step 2: greeting prompt uses display_name only (never auth).
                std::string prompt;
                auto u8s = [](const char8_t* text) {
                    return std::string(reinterpret_cast<const char*>(text));
                };
                prompt = u8s(u8"图中的人是") + present_display_name +
                         u8s(u8"，请用亲切温暖的方式叫出他/她的名字打招呼并嘘寒问暖。"
                             u8"只输出打招呼的话，不要解释。");

                ESP_LOGI(TAG, "[CAMERA] Face comparison complete; skipping VLM upload for presence-triggered photo");
                greeting = u8s(u8"欢迎回来，") + present_display_name + u8s(u8"。");
                state = CaptureState::GREETING;
                break;
            }

            case CaptureState::GREETING: {
                ESP_LOGD(TAG, "CaptureTask: GREETING");
                cam_mgr.Release();
                esp_timer_stop(zombie_timer_);
                if (display) {
                    app.Schedule([display]() {
                        if (!display->IsStandbyClockActive()) display->SetEmotion("happy");
                    });
                }
                std::string g = greeting;
                std::string fid = resolved_face_id;
                app.Schedule([this, fid, g]() { TriggerGreeting(fid, g); });
                state = CaptureState::DONE;
                break;
            }

            // 鈹€鈹€ 缁堟€侊細DONE 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
            case CaptureState::DONE:
                ESP_LOGD(TAG, "CaptureTask: DONE");
                vTaskDelete(nullptr);
                return;

            // 鈹€鈹€ 缁堟€侊細FAIL_HW锛堢‖浠舵晠闅滐級鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
            // 纭欢鏁呴殰鏃朵笉閲嶇疆 cooldown锛岄伩鍏嶇珛鍒诲啀娆¤Е鍙戯紙绛?cooldown 鑷劧鍒版湡锛?            // camera_acquired=false 鏃?mutex 鏈寔鏈夛紝鍙仛鏂數鍏滃簳锛涘惁鍒欐甯?Release
            case CaptureState::FAIL_HW:
                if (camera_acquired) {
                    cam_mgr.Release();
                } else {
                    cam_mgr.EnsurePowerOff();
                }
                esp_timer_stop(zombie_timer_);
                ESP_LOGW(TAG, "CaptureTask: hardware failure, keeping cooldown (no reset)");
                ESP_LOGD(TAG, "CaptureTask: FAIL_HW, cooldown kept");
                {
                    const uint32_t gen = capture_presence_generation_;
                    app.Schedule([gen]() {
                        ProactiveWakeCoordinator::GetInstance()
                            .OnFaceVerificationFailed(gen, "fail_hw");
                    });
                }
                if (display) {
                    app.Schedule([display]() { display->SetEmotion("neutral"); });
                }
                vTaskDelete(nullptr);
                return;

            case CaptureState::FAIL_NET:
                if (camera_acquired) cam_mgr.Release();
                else cam_mgr.EnsurePowerOff();
                esp_timer_stop(zombie_timer_);
                ESP_LOGW(TAG, "CaptureTask: network/server failure, resetting cooldown");
                ESP_LOGD(TAG, "CaptureTask: FAIL_NET, cooldown reset");
                presence_sensor_->ResetCooldown();
                {
                    const uint32_t gen = capture_presence_generation_;
                    app.Schedule([gen]() {
                        ProactiveWakeCoordinator::GetInstance()
                            .OnFaceVerificationFailed(gen, "fail_net");
                    });
                }
                if (display) {
                    app.Schedule([display]() { display->SetEmotion("neutral"); });
                }
                vTaskDelete(nullptr);
                return;

            case CaptureState::ABORTED:
                if (camera_acquired) cam_mgr.Release();
                else cam_mgr.EnsurePowerOff();
                esp_timer_stop(zombie_timer_);
                ESP_LOGW(TAG, "CaptureTask: aborted by external signal");
                ESP_LOGD(TAG, "CaptureTask: ABORTED");
                presence_sensor_->ResetCooldown();
                {
                    const uint32_t gen = capture_presence_generation_;
                    app.Schedule([gen]() {
                        ProactiveWakeCoordinator::GetInstance()
                            .OnFaceVerificationFailed(gen, "aborted");
                    });
                }
                if (display) {
                    app.Schedule([display]() { display->SetEmotion("neutral"); });
                }
                vTaskDelete(nullptr);
                return;
            }
        }
    }

    bool state_callback_registered_ = false;

    // 涓荤嚎绋嬫墽琛岋細鎵撳紑闊抽閫氶亾锛屾敞鍏?greeting 瑙﹀彂 TTS
    void TriggerGreeting(const std::string& face_id, const std::string& greeting) {
        auto& app = Application::GetInstance();
        // Route through Application::OnPersonIdentified → ProactiveWakeCoordinator
        // with the capture generation already stored in PresenceContext.
        (void)capture_presence_generation_;
        app.OnPersonIdentified(face_id, EscapeForJsonString(greeting));

        if (!state_callback_registered_) {
            state_callback_registered_ = true;
            DeviceStateEventManager::GetInstance().RegisterStateChangeCallback(
                [this](DeviceState prev, DeviceState curr) {
                    // 瀵硅瘽缁撴潫鍥?Idle 鏃讹細閲嶇疆 cooldown锛屽苟閫氱煡 CameraManager 閫€鍑?ENGAGED
                    if (curr == kDeviceStateIdle && prev != kDeviceStateIdle) {
                        if (presence_sensor_) {
                            presence_sensor_->ResetCooldown();
                        }
                        CameraManager::GetInstance().SetEngaged(false);
                        UserContext::GetInstance().ClearSessionUserId();
                    }
                    // 杩涘叆瀵硅瘽鏃讹細閫氱煡 CameraManager 杩涘叆 ENGAGED锛屽睆钄借嚜鍔ㄦ墦鎷涘懠
                    if (curr == kDeviceStateListening || curr == kDeviceStateSpeaking) {
                        CameraManager::GetInstance().SetEngaged(true);
                    }
                });
        }
    }

    // JSON 瀛楃涓茶浆涔夛紙闃叉 greeting 閲岀殑寮曞彿鐮村潖 JSON锛?    static std::string EscapeForJsonString(const std::string& s) {
    static std::string EscapeForJsonString(const std::string& s) {
        std::string out;
        out.reserve(s.size());
        for (char c : s) {
            if (c == '"')       out += "\\\"";
            else if (c == '\\') out += "\\\\";
            else if (c == '\n') out += "\\n";
            else if (c == '\r') out += "\\r";
            else                out += c;
        }
        return out;
    }

    void InitializeI2c() {
        i2c_master_bus_config_t i2c_bus_cfg = {
            .i2c_port = (i2c_port_t)1,
            .sda_io_num = AUDIO_CODEC_I2C_SDA_PIN,
            .scl_io_num = AUDIO_CODEC_I2C_SCL_PIN,
            .clk_source = I2C_CLK_SRC_DEFAULT,
            .glitch_ignore_cnt = 7,
            .intr_priority = 0,
            .trans_queue_depth = 0,
            .flags = {
                .enable_internal_pullup = 1,
            },
        };
        ESP_ERROR_CHECK(i2c_new_master_bus(&i2c_bus_cfg, &i2c_bus_));
    }

    void InitializeSpi() {
        spi_bus_config_t buscfg = {};
        buscfg.mosi_io_num = GPIO_NUM_6;
        buscfg.miso_io_num = GPIO_NUM_NC;
        buscfg.sclk_io_num = GPIO_NUM_7;
        buscfg.quadwp_io_num = GPIO_NUM_NC;
        buscfg.quadhd_io_num = GPIO_NUM_NC;
        buscfg.max_transfer_sz = DISPLAY_WIDTH * DISPLAY_HEIGHT * sizeof(uint16_t);
        ESP_ERROR_CHECK(spi_bus_initialize(SPI3_HOST, &buscfg, SPI_DMA_CH_AUTO));
    }

#ifdef TOUCH_I2C_SDA_PIN
    void InitializeTouch() {
        touch::TouchManagerConfig cfg = {
            .sda = TOUCH_I2C_SDA_PIN,
            .scl = TOUCH_I2C_SCL_PIN,
            .int_pin = TOUCH_INT_PIN,
            .rst_pin = TOUCH_RST_PIN,
            .display_width = DISPLAY_WIDTH,
            .display_height = DISPLAY_HEIGHT,
            .swap_xy = TOUCH_SWAP_XY,
            .mirror_x = TOUCH_MIRROR_X,
            .mirror_y = TOUCH_MIRROR_Y,
            .chip_type = touch::TouchChipType::FT6336,
            .i2c_addr = 0x48,
        };
        if (touch_manager_.Init(cfg, i2c_bus_)) {
            ESP_LOGI(TAG, "TouchManager (FT6336U) initialized");
            gesture_engine_.SetTouchManager(&touch_manager_);
            gesture_handler_.SetBoard(this);
            gesture_handler_.Attach(&gesture_engine_);
            esp_timer_create_args_t targs = {
                .callback = [](void* arg) {
                    auto* b = static_cast<EspBox3Board*>(arg);
                    b->gesture_engine_.Update(esp_timer_get_time() / 1000);
                },
                .arg = this,
                .dispatch_method = ESP_TIMER_TASK,
                .name = "gesture",
                .skip_unhandled_events = true
            };
            if (esp_timer_create(&targs, &gesture_timer_) == ESP_OK) {
                // Match the existing 10ms touch sampler; do not miss a short release.
                esp_timer_start_periodic(gesture_timer_, 10000);
            }
        }
    }
#endif

    void InitializeButtons() {
        boot_button_.OnClick([this]() {
            auto& app = Application::GetInstance();
            app.ToggleChatState();
        });

        boot_button_.OnLongPress([this]() {
            ResetWifiConfiguration();
        });

#if CONFIG_USE_DEVICE_AEC
        boot_button_.OnDoubleClick([this]() {
            auto& app = Application::GetInstance();
            if (app.GetDeviceState() == kDeviceStateIdle) {
                app.SetAecMode(app.GetAecMode() == kAecOff ? kAecOnDeviceSide : kAecOff);
            }
        });
#endif
    }

    void InitializeSt7796Display() {
        InitializeHomeRenderConfig();
        esp_lcd_panel_io_handle_t panel_io = nullptr;
        esp_lcd_panel_handle_t panel = nullptr;

        ESP_LOGD(TAG, "LCD config: size=%dx%d mirror_x=%d mirror_y=%d swap_xy=%d offset=(%d,%d)",
                 DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY,
                 DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y);
        ESP_LOGD(TAG, "Install panel IO");
        esp_lcd_panel_io_spi_config_t io_config = {};
        io_config.cs_gpio_num = GPIO_NUM_5;
        io_config.dc_gpio_num = GPIO_NUM_4;
        io_config.spi_mode = 0;
        io_config.pclk_hz = cubicat::HomeLcdSpiMHz() * 1000 * 1000;
        io_config.trans_queue_depth = 10;
        io_config.lcd_cmd_bits = 8;
        io_config.lcd_param_bits = 8;
        ESP_LOGD(TAG, "LCD SPI: pclk=%dHz queue=%d cs=%d dc=%d sclk=%d mosi=%d",
                 io_config.pclk_hz, io_config.trans_queue_depth, GPIO_NUM_5, GPIO_NUM_4, GPIO_NUM_7, GPIO_NUM_6);
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(SPI3_HOST, &io_config, &panel_io));

        ESP_LOGD(TAG, "Install ST7796 LCD driver");
        st7796_vendor_config_t vendor_config = {
            .init_cmds = st7796_init_cmds,
            .init_cmds_size = sizeof(st7796_init_cmds) / sizeof(st7796_lcd_init_cmd_t),
        };

        esp_lcd_panel_dev_config_t panel_config = {};
        panel_config.reset_gpio_num = GPIO_NUM_48;
        panel_config.flags.reset_active_high = 1;
        panel_config.rgb_ele_order = LCD_RGB_ELEMENT_ORDER_BGR;
        panel_config.bits_per_pixel = 16;
        panel_config.vendor_config = &vendor_config;
        ESP_ERROR_CHECK(esp_lcd_new_panel_st7796(panel_io, &panel_config, &panel));
        esp_lcd_panel_reset(panel);
        esp_lcd_panel_init(panel);
        esp_lcd_panel_swap_xy(panel, DISPLAY_SWAP_XY);
        esp_lcd_panel_mirror(panel, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y);
        esp_lcd_panel_set_gap(panel, DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y);
        ESP_LOGD(TAG, "LCD panel rotation applied, gap set to x=%d y=%d",
                 DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y);
        esp_lcd_panel_disp_on_off(panel, true);

        display_ = new SpiLcdDisplay(panel_io, panel,
            DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY);
    }

public:
    EspBox3Board() : boot_button_(BOOT_BUTTON_GPIO) {
        esp_reset_reason_t reset_reason = esp_reset_reason();
        ESP_LOGW(TAG, "RESET_REASON=%d", static_cast<int>(reset_reason));

        // 鎸傝浇 userdata SPIFFS 鍒嗗尯锛堣涓烘棩蹇楋級锛屽繀椤诲湪浠讳綍鏃ュ織鍐欏叆鍓嶅畬鎴?        BehaviorLogger::Init();
        BehaviorLogger::Init();

        // Keep ESP_LOG on the configured USB Serial/JTAG console (flash port).
        ESP_LOGI(TAG, "Runtime logs use the USB Serial/JTAG console");

        gpio_config_t pwr_conf = {};
        pwr_conf.pin_bit_mask = (1ULL << 21);
        pwr_conf.mode = GPIO_MODE_OUTPUT;
        pwr_conf.pull_up_en = GPIO_PULLUP_DISABLE;
        pwr_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
        pwr_conf.intr_type = GPIO_INTR_DISABLE;
        gpio_config(&pwr_conf);
        gpio_set_level((gpio_num_t)21, 1);
        vTaskDelay(pdMS_TO_TICKS(100));

#if defined(CONFIG_USE_USB_STREAM) || defined(CONFIG_ESP_VIDEO_ENABLE_USB_UVC_VIDEO_DEVICE)
        if (!UsbConsoleConnectedAtBoot()) {
            const gpio_num_t usb_enable_pin = (gpio_num_t)USB_ENABLE_PIN;
            const int usb_power_off_level = !USB_ENABLE_ACTIVE_LEVEL;
            const int initial_enable_level = gpio_get_level(usb_enable_pin);
            ESP_LOGI(TAG, "USB VBUS switch: IO%d initial_level=%d active_level=%d",
                     usb_enable_pin, initial_enable_level, USB_ENABLE_ACTIVE_LEVEL);

            // Preload the inactive output latch before enabling the pin to
            // avoid a short unintended VBUS pulse during GPIO reconfiguration.
            gpio_set_level(usb_enable_pin, usb_power_off_level);
            gpio_config_t usb_power_conf = {};
            usb_power_conf.pin_bit_mask = (1ULL << USB_ENABLE_PIN);
            // Keep the input path enabled so gpio_get_level() reads the pad
            // level instead of always returning zero for an output-only pin.
            usb_power_conf.mode = GPIO_MODE_INPUT_OUTPUT;
            usb_power_conf.pull_up_en = GPIO_PULLUP_DISABLE;
            usb_power_conf.pull_down_en = GPIO_PULLDOWN_DISABLE;
            usb_power_conf.intr_type = GPIO_INTR_DISABLE;

            esp_err_t usb_power_ret = gpio_config(&usb_power_conf);
            if (usb_power_ret == ESP_OK) {
                gpio_set_level(usb_enable_pin, usb_power_off_level);
                ESP_LOGI(TAG, "USB camera VBUS held OFF: IO%d level=%d, waiting %dms before Host init",
                         usb_enable_pin, gpio_get_level(usb_enable_pin),
                         USB_POWER_OFF_DELAY_MS);
                vTaskDelay(pdMS_TO_TICKS(USB_POWER_OFF_DELAY_MS));
            } else {
                ESP_LOGE(TAG, "USB VBUS switch GPIO configuration failed: %s",
                         esp_err_to_name(usb_power_ret));
            }

            ESP_LOGI(TAG, "Starting USB Host while camera VBUS is OFF...");

#ifdef CONFIG_USE_USB_STREAM
            // Start the Host once and keep it alive, matching the official
            // usb_stream lifecycle.  This monitor also normalizes USB tasks
            // created by a later hot-plug so Opus remains responsive.
            TaskHandle_t usb_cam_init_handle = nullptr;
            xTaskCreate([](void* arg) {
                task_diag::LogCurrentTask("EspBox3Board", "usb_cam_init_start", 3, -1);
                auto* board = static_cast<EspBox3Board*>(arg);
                size_t free_dma = heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA);
                size_t block_dma = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA);
                ESP_LOGI("EspBox3Board",
                         "Starting persistent USB Host (dma_free=%u largest=%u)",
                         (unsigned)free_dma, (unsigned)block_dma);

                auto& camera_manager = CameraManager::GetInstance();
                if (!camera_manager.OpenPersistentStream()) {
                    ESP_LOGE("EspBox3Board", "Persistent USB Host failed to start; no automatic teardown retry");
                    vTaskDelete(nullptr);
                    return;
                }
                LogUsbWorkerTask("usb_proc");
                LogUsbWorkerTask("usb_stream_proc");
                LogUsbWorkerTask("sample_proc");

                // usb_streaming_start() returns only after USB_HOST_INIT_DONE,
                // so powering the camera here creates a clean attach edge for
                // an already-listening Host controller.
                gpio_set_level((gpio_num_t)USB_ENABLE_PIN, USB_ENABLE_ACTIVE_LEVEL);
                ESP_LOGI("EspBox3Board",
                         "USB Host ready; camera VBUS ON: IO%d level=%d, stabilizing %dms",
                         USB_ENABLE_PIN,
                         gpio_get_level((gpio_num_t)USB_ENABLE_PIN),
                         USB_POWER_STABILIZE_DELAY_MS);
                vTaskDelay(pdMS_TO_TICKS(50));
                vTaskDelay(pdMS_TO_TICKS(USB_POWER_STABILIZE_DELAY_MS));

                ESP_LOGI("EspBox3Board", "Persistent USB Host started; monitoring UVC hot-plug");
                constexpr int64_t kEnumerationPriorityWindowUs = 6000000;
                const int64_t enumeration_deadline = esp_timer_get_time() + kEnumerationPriorityWindowUs;
                bool runtime_priorities_applied = false;
                bool was_ready = false;
                while (true) {
                    if (gpio_get_level((gpio_num_t)USB_ENABLE_PIN) != USB_ENABLE_ACTIVE_LEVEL) {
                        ESP_LOGE("EspBox3Board",
                                 "USB VBUS enable IO%d unexpectedly inactive; restoring level=%d",
                                 USB_ENABLE_PIN, USB_ENABLE_ACTIVE_LEVEL);
                        gpio_set_level((gpio_num_t)USB_ENABLE_PIN, USB_ENABLE_ACTIVE_LEVEL);
                    }
                    const bool is_ready = camera_manager.IsStreamReady();
                    if (!runtime_priorities_applied &&
                        (is_ready || esp_timer_get_time() >= enumeration_deadline)) {
                        NormalizeUsbRuntimePriorities();
                        runtime_priorities_applied = true;
                        ESP_LOGI("EspBox3Board",
                                 "USB enumeration priority window ended; runtime priorities active");
                    } else if (runtime_priorities_applied) {
                        // sample_proc is created only after UVC enumeration, so
                        // keep enforcing its runtime priority after hot-plug.
                        NormalizeUsbRuntimePriorities();
                    }
                    if (is_ready && !was_ready) {
                        ESP_LOGI("EspBox3Board", "USB camera stream became ready");
                        if (board->presence_sensor_ != nullptr) {
                            board->presence_sensor_->RequestStableRecheck();
                        }
                    } else if (!is_ready && was_ready) {
                        ESP_LOGW("EspBox3Board", "USB camera disconnected; Host remains active for reconnect");
                    }
                    was_ready = is_ready;
                    vTaskDelay(pdMS_TO_TICKS(500));
                }
            }, "usb_cam_init", 4096, this, 3, &usb_cam_init_handle);
            task_diag::LogTaskHandle(TAG, "usb_cam_init_created", usb_cam_init_handle, 3, -1);
#else
            esp_video_init_config_t uvc_cfg = {};
            static esp_video_init_usb_uvc_config_t uvc_dev_cfg = {};
            uvc_dev_cfg.usb.init_usb_host_lib = true;
            uvc_dev_cfg.usb.task_stack        = 4096;
            uvc_dev_cfg.usb.task_priority     = 5;
            uvc_dev_cfg.usb.task_affinity     = -1;
            uvc_dev_cfg.uvc.uvc_dev_num       = 1;
            uvc_dev_cfg.uvc.task_stack        = 5120;
            uvc_dev_cfg.uvc.task_priority     = 5;
            uvc_dev_cfg.uvc.task_affinity     = -1;
            uvc_cfg.usb_uvc = &uvc_dev_cfg;
            esp_err_t vret = esp_video_init(&uvc_cfg);
            if (vret == ESP_OK) {
                CameraManager::GetInstance().MarkVideoInitDone();
                gpio_set_level(usb_enable_pin, USB_ENABLE_ACTIVE_LEVEL);
                ESP_LOGI(TAG, "USB video Host ready; camera VBUS ON: IO%d level=%d, stabilizing %dms",
                         usb_enable_pin, gpio_get_level(usb_enable_pin),
                         USB_POWER_STABILIZE_DELAY_MS);
                vTaskDelay(pdMS_TO_TICKS(USB_POWER_STABILIZE_DELAY_MS));
                int64_t t0 = esp_timer_get_time();
                bool cam_ready = false;
                while ((esp_timer_get_time() - t0) < 8000000LL) {
                    if (CameraManager::GetInstance().IsUvcDeviceConnected()) {
                        cam_ready = true;
                        break;
                    }
                    vTaskDelay(pdMS_TO_TICKS(200));
                }
                if (cam_ready) {
                    vTaskDelay(pdMS_TO_TICKS(3000));
                    for (int retry = 0; retry < 3; retry++) {
                        if (CameraManager::GetInstance().OpenPersistentStream()) {
                            ESP_LOGI(TAG, "Persistent stream opened OK (attempt %d)", retry + 1);
                            break;
                        }
                        vTaskDelay(pdMS_TO_TICKS(2000));
                    }
                } else {
                    ESP_LOGW(TAG, "USB camera not enumerated after 8s");
                }
            } else {
                ESP_LOGW(TAG, "esp_video_init FAILED: %s", esp_err_to_name(vret));
            }
#endif
        } else {
            ESP_LOGI(TAG, "USB mode=console: PC connected; PHY reserved for flash-port logs. Switch to UVC and reboot for camera mode.");
        }
#endif

        InitializeI2c();

        // Take ownership of the backlight GPIO before resetting or enabling
        // the LCD.  Until LEDC configures GPIO47 the pin can briefly expose
        // the controller's undefined power-on GRAM, which looks like several
        // corrupted frames during boot.
        auto* boot_backlight = GetBacklight();
        boot_backlight->SetBrightness(0);
        ESP_LOGI(TAG, "Backlight held off before LCD initialization");

        InitializeSpi();
        InitializeSt7796Display();
        auto* boot_display = static_cast<LcdDisplay*>(display_);
        boot_display->SetStartupRevealCallback([boot_backlight]() {
            ESP_LOGI(TAG,
                     "First native frame committed; fading in backlight");
            boot_backlight->RestoreBrightness(true);
        });
        vTaskDelay(pdMS_TO_TICKS(100));
#ifdef TOUCH_I2C_SDA_PIN
        InitializeTouch();
#endif
        InitializeButtons();

        // 鍒濆鍖栦汉浣撳瓨鍦ㄤ紶鎰熷櫒锛堝紓姝ワ紝涓嶉樆濉炲惎鍔級
        // 娉ㄦ剰锛歊egisterStateChangeCallback 涓嶅湪杩欓噷璋冪敤锛?        // 鍥犱负 Board 鏋勯€犳椂 esp_event_loop 鍙兘灏氭湭灏辩华銆?        // Cooldown 鐨勬竻闄ゆ敼涓哄湪 OnPresenceDetected 閲岄€氳繃妫€鏌ョ姸鎬佸疄鐜般€?        InitializePresenceSensor();
        InitializePresenceSensor();

#if defined(CONFIG_USE_USB_STREAM) || defined(CONFIG_ESP_VIDEO_ENABLE_USB_UVC_VIDEO_DEVICE)
        if (CameraManager::GetInstance().IsUvcDeviceConnected()) {
            ESP_LOGI(TAG, "USB camera ready.");
        } else {
            ESP_LOGW(TAG, "USB camera NOT ready after Board construction!");
        }
#endif

        struct HomeInitContext {
            LcdDisplay* display;
            SemaphoreHandle_t complete;
        };
        auto* home_display = static_cast<LcdDisplay*>(display_);
        SemaphoreHandle_t home_init_complete = xSemaphoreCreateBinary();
        if (home_display == nullptr || home_init_complete == nullptr) {
            ESP_LOGE(TAG, "Unable to prepare serialized Cubicat Home init");
        } else {
            HomeInitContext context{
                .display = home_display,
                .complete = home_init_complete,
            };
            const BaseType_t home_task_result = xTaskCreate(
                [](void* arg) {
                    auto* context =
                        static_cast<HomeInitContext*>(arg);
                    ESP_LOGI(
                        TAG,
                        "Starting serialized Cubicat Home after "
                        "board hardware init");
                    context->display->StartCubicatHome();
                    xSemaphoreGive(context->complete);
                    vTaskDelete(nullptr);
                },
                "home_init",
                16384,
                &context,
                2,
                nullptr);
            if (home_task_result != pdPASS) {
                ESP_LOGE(TAG,
                         "Failed to create serialized Cubicat Home init task");
            } else {
                xSemaphoreTake(home_init_complete, portMAX_DELAY);
                ESP_LOGI(TAG,
                         "Serialized Cubicat Home init complete; "
                         "application startup may continue");
            }
            vSemaphoreDelete(home_init_complete);
        }
    }

    touch::TouchManager* GetTouchManager() { return touch_manager_.IsInitialized() ? &touch_manager_ : nullptr; }
    touch::GestureEngine* GetGestureEngine() override { return touch_manager_.IsInitialized() ? &gesture_engine_ : nullptr; }

    virtual AudioCodec* GetAudioCodec() override {
        static BoxAudioCodec audio_codec(
            i2c_bus_, 
            AUDIO_INPUT_SAMPLE_RATE, 
            AUDIO_OUTPUT_SAMPLE_RATE,
            AUDIO_I2S_GPIO_MCLK, 
            AUDIO_I2S_GPIO_BCLK, 
            AUDIO_I2S_GPIO_WS, 
            AUDIO_I2S_GPIO_DOUT, 
            AUDIO_I2S_GPIO_DIN,
            AUDIO_CODEC_PA_PIN, 
            AUDIO_CODEC_ES8311_ADDR, 
            AUDIO_CODEC_ES7210_ADDR, 
            AUDIO_INPUT_REFERENCE);
        return &audio_codec;
    }

    virtual Display* GetDisplay() override {
        return display_;
    }

    virtual Backlight* GetBacklight() override {
        static PwmBacklight backlight(DISPLAY_BACKLIGHT_PIN, DISPLAY_BACKLIGHT_OUTPUT_INVERT,
                                      DISPLAY_BACKLIGHT_PWM_FREQ_HZ);
        return &backlight;
    }

    // GetCamera() 杩斿洖 CameraManager 褰撳墠鎸佹湁鐨勬憚鍍忓ご瀹炰緥锛堟湭 Acquire 鏃朵负 nullptr锛?    virtual Camera* GetCamera() override {
    virtual Camera* GetCamera() override {
        return CameraManager::GetInstance().GetCamera();
    }
};

DECLARE_BOARD(EspBox3Board);
