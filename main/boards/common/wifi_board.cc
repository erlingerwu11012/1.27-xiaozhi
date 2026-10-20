#include "wifi_board.h"

#include "display.h"
#include "application.h"
#include "system_info.h"
#include "settings.h"
#include "boards/common/brightness_levels.h"
#include "assets/lang_config.h"
#include "ota_tls_diag.h"

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include "esp_network.h"
#include <esp_log.h>
#include <esp_wifi.h>
#include <esp_event.h>
#include <esp_system.h>
#include <nvs_flash.h>
#include <string>

// esp-wifi-connect WifiConfigurationAp (DNS hijack + captive portal auto-redirect)
#include <wifi_configuration_ap.h>
#include <wifi_station.h>
#include <ssid_manager.h>

static const char *TAG = "WifiBoard";

namespace {
constexpr const char* kNetworkWifi = "wifi";
constexpr const char* kNetworkOffline = "wifi_off";
constexpr const char* kNetworkFair = "wifi_fair";
constexpr const char* kNetworkWeak = "wifi_weak";
}  // namespace

WifiBoard::WifiBoard() {
    Settings settings("wifi", true);
    wifi_config_mode_ = settings.GetInt("force_ap") == 1;
    if (wifi_config_mode_) {
        ESP_LOGI(TAG, "force_ap is set to 1, reset to 0");
        settings.SetInt("force_ap", 0);
    }
}

std::string WifiBoard::GetBoardType() {
    return "wifi";
}

// 进入配网模式（原版小智方式：esp-wifi-connect WifiConfigurationAp，含 DNS 劫持 + captive portal 自动跳转）
void WifiBoard::EnterWifiConfigMode() {
    auto& application = Application::GetInstance();
    application.SetDeviceState(kDeviceStateWifiConfiguring);
    application.PlaySound(Lang::Sounds::OGG_WIFICONFIG);

    // 0. 确保 NVS、netif、event loop 已初始化
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }
    esp_netif_init();
    if (esp_event_loop_create_default() != ESP_OK) {
        ESP_LOGW(TAG, "Event loop might be already created");
    }

    // 1. 若已配网失败进入的，清除旧配置
    Settings settings("wifi", true);
    std::string saved_ssid = settings.GetString("ssid");
    if (!saved_ssid.empty()) {
        ESP_LOGW(TAG, "Clearing failed credentials for re-provisioning");
        settings.SetString("ssid", "");
        settings.SetString("password", "");
        SsidManager::GetInstance().Clear();
    }

    // 2. 初始化 WiFi（WifiConfigurationAp 依赖）
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    err = esp_wifi_init(&cfg);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "esp_wifi_init: %d (may already inited)", err);
    }

    // 3. 启动 WifiConfigurationAp 单例（含 DnsServer + captive portal）
    auto& config_ap = WifiConfigurationAp::GetInstance();
    config_ap.SetSsidPrefix("Xiaozhi_Prov");
    config_ap.SetLanguage("zh-CN");
    config_ap.Start();

    // 4. 显示配网提示（连接后手机会自动弹出配网页，无需手动输入 192.168.4.1）
    auto display = Board::GetInstance().GetDisplay();
    if (display) {
        display->ShowNotification(
            "1. Connect WiFi: Xiaozhi_Prov_xxxx\n"
            "2. 打开浏览器访问 192.168.4.1",
            30000);
    }

    ESP_LOGI(TAG, "Config AP started with captive portal (auto redirect)");

    // 5. 轮询等待用户提交配网表单（不再重启，配网成功后直接连接）
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(2000));
        auto& ssid_list = SsidManager::GetInstance().GetSsidList();
        if (!ssid_list.empty() && !ssid_list[0].ssid.empty()) {
            ESP_LOGI(TAG, "Got credentials from config page");
            settings.SetString("ssid", ssid_list[0].ssid);
            settings.SetString("password", ssid_list[0].password);
            if (display) {
                display->ShowNotification("配网成功，正在重启连接...");
            }
            config_ap.Stop();
            vTaskDelay(pdMS_TO_TICKS(500));  /* 给用户看到提示的时间 */
            esp_restart();  /* 重启后以干净的 netif 状态重新连接，避免重复创建 netif 崩溃 */
        }
    }
}

// 启动网络逻辑
void WifiBoard::StartNetwork() {
    // 基础初始化
    static bool netif_initialized = false;
    if (!netif_initialized) {
        ESP_LOGI(TAG, "Initializing Netif and NVS...");
        esp_err_t err = nvs_flash_init();
        if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
            nvs_flash_erase();
            nvs_flash_init();
        }
        esp_netif_init();
        if (esp_event_loop_create_default() != ESP_OK) {
            ESP_LOGW(TAG, "Event loop might be already created");
        }
        netif_initialized = true;
    }

    // 1. 强制配网：进入配网模式，配网成功后直接返回（不重启）
    if (wifi_config_mode_) {
        ESP_LOGI(TAG, "Force config mode flag set");
        EnterWifiConfigMode();
        wifi_config_mode_ = false;
    }

    ESP_LOGI(TAG, "Starting WifiStation...");
    auto& wifi_station = WifiStation::GetInstance();
    wifi_station.OnScanBegin([this]() {
        auto display = Board::GetInstance().GetDisplay();
        if (!display) return;
        // 扫描阶段
        display->SetEmotion("sleepy");
        display->ShowNotification(Lang::Strings::SCANNING_WIFI, 30000);
    });
    wifi_station.OnConnect([this](const std::string& ssid) {
        auto display = Board::GetInstance().GetDisplay();
        if (!display) return;
        std::string s = Lang::Strings::CONNECT_TO; s += ssid;
        display->ShowNotification(s.c_str(), 30000);
        // 连接中
        display->SetEmotion("sleepy");
    });
    wifi_station.OnConnected([this](const std::string& ssid) {
        auto display = Board::GetInstance().GetDisplay();
        if (!display) return;
        std::string s = Lang::Strings::CONNECTED_TO; s += ssid;
        display->ShowNotification(s.c_str(), 2000);
        // 先睁大眼睛（惊讶一下）
        display->SetEmotion("happy");
        // 1.5 秒后回到日常表情
        static esp_timer_handle_t wakeup_timer = nullptr;
        if (!wakeup_timer) {
            esp_timer_create_args_t args = {
                .callback = [](void*){
                    auto d = Board::GetInstance().GetDisplay();
                    if (d) d->SetEmotion("neutral");
                },
                .arg = nullptr,
                .dispatch_method = ESP_TIMER_TASK,
                .name = "wifi_wakeup",
                .skip_unhandled_events = false,
            };
            ESP_ERROR_CHECK(esp_timer_create(&args, &wakeup_timer));
        }
        esp_timer_stop(wakeup_timer);
        ESP_ERROR_CHECK(esp_timer_start_once(wakeup_timer, 1500 * 1000));
    });
    wifi_station.Start();

    // 2. 注入凭证并连接（含配网返回后的重试）
    for (;;) {
        Settings settings("wifi", true);
        std::string saved_ssid = settings.GetString("ssid");
        std::string saved_password = settings.GetString("password");

        if (!saved_ssid.empty()) {
            ESP_LOGI(TAG, "Injecting credentials: %s", saved_ssid.c_str());
            wifi_config_t wifi_cfg;
            memset(&wifi_cfg, 0, sizeof(wifi_config_t));
            size_t ssid_len = saved_ssid.length() > 31 ? 31 : saved_ssid.length();
            size_t pass_len = saved_password.length() > 63 ? 63 : saved_password.length();
            memcpy(wifi_cfg.sta.ssid, saved_ssid.c_str(), ssid_len);
            memcpy(wifi_cfg.sta.password, saved_password.c_str(), pass_len);
            esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg);
            esp_wifi_connect();
            // Externally powered product: keep modem always awake.
            esp_wifi_set_ps(WIFI_PS_NONE);

            if (wifi_station.WaitForConnected(15 * 1000)) {
                OtaTlsDiag::NoteWifiGotIp();
                esp_wifi_set_ps(WIFI_PS_NONE);
                return;
            }
            ESP_LOGW(TAG, "Connection timeout. Entering provisioning...");
            auto display = Board::GetInstance().GetDisplay();
            if (display) display->SetEmotion("sad");
        } else {
            ESP_LOGW(TAG, "No credentials. Entering provisioning directly...");
        }

        wifi_station.Stop();
        vTaskDelay(pdMS_TO_TICKS(500));
        EnterWifiConfigMode();
        wifi_station.Start();
    }
}

NetworkInterface* WifiBoard::GetNetwork() {
    static EspNetwork network;
    static bool wifi_events_hooked = false;
    if (!wifi_events_hooked) {
        wifi_events_hooked = true;
        esp_event_handler_register(
            WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED,
            [](void*, esp_event_base_t, int32_t, void* event_data) {
                auto* disc =
                    static_cast<wifi_event_sta_disconnected_t*>(event_data);
                const int reason = disc ? disc->reason : 0;
                EspWebSocket::NoteWifiDisconnectReason(reason);
                ESP_LOGW(TAG,
                         "[WS_DIAG] wifi_sta_disconnected reason=%d",
                         reason);
            },
            nullptr);
    }
    return &network;
}

const char* WifiBoard::GetNetworkStateIcon() {
    if (wifi_config_mode_) {
        return kNetworkWifi;
    }
    auto& wifi_station = WifiStation::GetInstance();
    if (!wifi_station.IsConnected()) {
        return kNetworkOffline;
    }
    int8_t rssi = wifi_station.GetRssi();
    if (rssi >= -60) {
        return kNetworkWifi;
    } else if (rssi >= -70) {
        return kNetworkFair;
    } else {
        return kNetworkWeak;
    }
}

std::string WifiBoard::GetBoardJson() {
    auto& wifi_station = WifiStation::GetInstance();
    std::string board_json = R"({)";
    board_json += R"("type":")" + std::string(BOARD_TYPE) + R"(",)";
    board_json += R"("name":")" + std::string(BOARD_NAME) + R"(",)";
    if (!wifi_config_mode_) {
        board_json += R"("ssid":")" + wifi_station.GetSsid() + R"(",)";
        board_json += R"("rssi":)" + std::to_string(wifi_station.GetRssi()) + R"(,)";
        board_json += R"("channel":)" + std::to_string(wifi_station.GetChannel()) + R"(,)";
        board_json += R"("ip":")" + wifi_station.GetIpAddress() + R"(",)";
    }
    board_json += R"("mac":")" + SystemInfo::GetMacAddress() + R"(")";
    board_json += R"(})";
    return board_json;
}

void WifiBoard::SetPowerSaveMode(bool /*enabled*/) {
    // 设备为外接电源产品，禁止启用 Wi‑Fi power save。
    esp_err_t err = esp_wifi_set_ps(WIFI_PS_NONE);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "Force WIFI_PS_NONE failed err=0x%x", err);
    }
}

void WifiBoard::ResetWifiConfiguration() {
    {
        Settings settings("wifi", true);
        settings.SetInt("force_ap", 1);
    }
    GetDisplay()->ShowNotification(Lang::Strings::ENTERING_WIFI_CONFIG_MODE);
    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_restart();
}

std::string WifiBoard::GetDeviceStatusJson() {
    auto& board = Board::GetInstance();
    auto root = cJSON_CreateObject();

    // Audio speaker
    auto audio_speaker = cJSON_CreateObject();
    auto audio_codec = board.GetAudioCodec();
    if (audio_codec) {
        cJSON_AddNumberToObject(audio_speaker, "volume", audio_codec->output_volume());
    }
    cJSON_AddItemToObject(root, "audio_speaker", audio_speaker);

    // Screen brightness
    auto backlight = board.GetBacklight();
    auto screen = cJSON_CreateObject();
    if (backlight) {
        const int level = BrightnessLevelFromStored(backlight->normal_brightness());
        const uint16_t duty = BrightnessDutyCount(backlight->brightness());
        cJSON_AddNumberToObject(screen, "brightness", level);
        cJSON_AddNumberToObject(screen, "brightness_level", level);
        cJSON_AddNumberToObject(screen, "duty_percent", duty * 100.0 / 1023.0);
    }
    auto display = board.GetDisplay();
    if (display && display->height() > 64) { 
        auto theme = display->GetTheme();
        if (theme != nullptr) {
            cJSON_AddStringToObject(screen, "theme", theme->name().c_str());
        }
    }
    cJSON_AddItemToObject(root, "screen", screen);

    // Battery
    int battery_level = 0;
    bool charging = false;
    bool discharging = false;
    if (board.GetBatteryLevel(battery_level, charging, discharging)) {
        cJSON* battery = cJSON_CreateObject();
        cJSON_AddNumberToObject(battery, "level", battery_level);
        cJSON_AddBoolToObject(battery, "charging", charging);
        cJSON_AddItemToObject(root, "battery", battery);
    }

    // Network
    auto network = cJSON_CreateObject();
    auto& wifi_station = WifiStation::GetInstance();
    cJSON_AddStringToObject(network, "type", "wifi");
    cJSON_AddStringToObject(network, "ssid", wifi_station.GetSsid().c_str());
    int rssi = wifi_station.GetRssi();
    if (rssi >= -60) {
        cJSON_AddStringToObject(network, "signal", "strong");
    } else if (rssi >= -70) {
        cJSON_AddStringToObject(network, "signal", "medium");
    } else {
        cJSON_AddStringToObject(network, "signal", "weak");
    }
    cJSON_AddItemToObject(root, "network", network);

    // Chip Temperature
    float esp32temp = 0.0f;
    if (board.GetTemperature(esp32temp)) {
        auto chip = cJSON_CreateObject();
        cJSON_AddNumberToObject(chip, "temperature", esp32temp);
        cJSON_AddItemToObject(root, "chip", chip);
    }

    auto json_str = cJSON_PrintUnformatted(root);
    std::string json(json_str);
    cJSON_free(json_str);
    cJSON_Delete(root);
    return json;
}
