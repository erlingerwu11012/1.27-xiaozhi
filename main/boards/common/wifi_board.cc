#include "wifi_board.h"

#include "display.h"
#include "application.h"
#include "system_info.h"
#include "settings.h"
#include "assets/lang_config.h"

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <esp_network.h>
#include <esp_log.h>
#include <esp_wifi.h>
#include <esp_event.h> 
#include <nvs_flash.h>
#include <string> // 🟢 确保包含 string 头文件

// 引入官方配网组件
#include <wifi_provisioning/manager.h>
#include <wifi_provisioning/scheme_ble.h>

#include <font_awesome.h>
#include <wifi_station.h>
#include <ssid_manager.h>

static const char *TAG = "WifiBoard";

// 配网事件回调
static void provisioning_event_handler(void* arg, esp_event_base_t event_base,
                                       int32_t event_id, void* event_data) {
    if (event_base == WIFI_PROV_EVENT) {
        switch (event_id) {
            case WIFI_PROV_START:
                ESP_LOGI(TAG, "BLE Provisioning started");
                break;
            case WIFI_PROV_CRED_RECV: {
                wifi_sta_config_t *wifi_sta_cfg = (wifi_sta_config_t *)event_data;
                ESP_LOGI(TAG, "Received Wi-Fi credentials");
                
                // 🟢 【保存】手动保存密码到 Settings
                Settings settings("wifi", true);
                std::string ssid_str((char*)wifi_sta_cfg->ssid);
                std::string password_str((char*)wifi_sta_cfg->password);
                settings.SetString("ssid", ssid_str);
                settings.SetString("password", password_str);
                ESP_LOGI(TAG, "Backup credentials saved to custom Settings");
                break;
            }
            case WIFI_PROV_CRED_FAIL: {
                // wifi_prov_sta_fail_reason_t *reason = (wifi_prov_sta_fail_reason_t *)event_data;
                ESP_LOGE(TAG, "Provisioning failed!");
                break;
            }
            case WIFI_PROV_CRED_SUCCESS:
                ESP_LOGI(TAG, "Provisioning successful");
                break;
            case WIFI_PROV_END:
                break;
            default:
                break;
        }
    }
}

extern "C" void wifi_prov_scheme_ble_event_cb_free_btdm(void *user_data, wifi_prov_cb_event_t event, void *event_data);

// 自定义 Scheme 事件处理器
static void custom_prov_scheme_ble_event_handler(void *user_data, wifi_prov_cb_event_t event, void *event_data) {
    if (event == WIFI_PROV_INIT) {
        wifi_prov_scheme_ble_event_cb_free_btdm(user_data, event, event_data);
    }
    else if (event == WIFI_PROV_DEINIT) {
        ESP_LOGI(TAG, "Custom handler: Skipping BT memory release on deinit");
    }
}

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

// 进入配网模式 (BLE 无密码)
void WifiBoard::EnterWifiConfigMode() {
    auto& application = Application::GetInstance();
    application.SetDeviceState(kDeviceStateWifiConfiguring);

    // 0. 确保 NVS 已初始化
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    // 1. 手动初始化 Wi-Fi 供配网使用
    esp_netif_t *netif = esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    err = esp_wifi_init(&cfg);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "esp_wifi_init failed (maybe already inited): %d", err);
    }
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_start();

    // 2. 初始化配网管理器
    wifi_prov_mgr_config_t config = {
        .scheme = wifi_prov_scheme_ble,
        .scheme_event_handler = custom_prov_scheme_ble_event_handler
    };

    if (wifi_prov_mgr_init(config) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to init wifi_prov_mgr");
        return;
    }

    // 3. 检查是否已配网
    bool provisioned = false;
    wifi_prov_mgr_is_provisioned(&provisioned);
    if (provisioned) {
        ESP_LOGW(TAG, "Already provisioned but failed to connect. Resetting...");
        wifi_prov_mgr_reset_provisioning();
        
        // 同步清除 Settings
        Settings settings("wifi", true);
        settings.SetString("ssid", "");
        settings.SetString("password", "");
    }

    // 4. 注册事件监听
    esp_event_handler_register(WIFI_PROV_EVENT, ESP_EVENT_ANY_ID, &provisioning_event_handler, NULL);

    // 5. 设置配网信息
    const char *service_name = "Xiaozhi_Prov";
    const char *service_key = NULL; 

    // === 🟢 扫码配网逻辑开始 🟢 ===
    
    // 构造二维码 Payload
    char qr_payload[150];
    snprintf(qr_payload, sizeof(qr_payload), 
             "{\"ver\":\"v1\",\"name\":\"%s\",\"transport\":\"ble\"}", 
             service_name);
    
    ESP_LOGI(TAG, "Provisioning QR Code generated: %s", qr_payload);

    // 使用 Schedule 异步调用显示，防止阻塞当前线程或导致栈溢出
    application.Schedule([qr_str = std::string(qr_payload)]() {
        auto display = Board::GetInstance().GetDisplay();
        if (display) {
            display->ShowQrCode(qr_str.c_str());
        }
    });

    // === 🔴 扫码配网逻辑结束 🔴 ===


    // ⚠️ 已注释掉 Alert，防止与二维码显示冲突
    // std::string hint = "蓝牙配网已启动\n使用微信小程序连接\n(无密码)";
    // application.Alert("蓝牙配网模式", hint.c_str(), "bluetooth", "");

    // 6. 开始广播
    err = wifi_prov_mgr_start_provisioning(WIFI_PROV_SECURITY_0, service_key, service_name, NULL);
    
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start provisioning: %d", err);
    } else {
        ESP_LOGI(TAG, "BLE Provisioning started. Name: %s", service_name);
    }

    // 7. 等待连接循环
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(1000));
        
        esp_netif_ip_info_t ip_info;
        if (netif != NULL && esp_netif_get_ip_info(netif, &ip_info) == ESP_OK) {
            if (ip_info.ip.addr != 0) {
                ESP_LOGI(TAG, "WiFi Connected! IP: " IPSTR, IP2STR(&ip_info.ip));
                
                auto display = Board::GetInstance().GetDisplay();
                // 收到配置后提示用户
                display->ShowNotification("配网成功，正在重启..."); 
                
                wifi_prov_mgr_stop_provisioning();
                vTaskDelay(pdMS_TO_TICKS(2000));
                
                ESP_LOGI(TAG, "Rebooting to apply new settings...");
                esp_restart();
                break; 
            }
        }
    }
}

// 启动网络逻辑
void WifiBoard::StartNetwork() {
    // 🟢 基础初始化
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

    // 1. 检查强制配网标记
    if (wifi_config_mode_) {
        ESP_LOGI(TAG, "Force config mode flag set");
        EnterWifiConfigMode();
        return; 
    }

    ESP_LOGI(TAG, "Starting WifiStation...");
    auto& wifi_station = WifiStation::GetInstance();
    
    // 注册显示回调
    wifi_station.OnScanBegin([this]() {
        Board::GetInstance().GetDisplay()->ShowNotification(Lang::Strings::SCANNING_WIFI, 30000);
    });
    wifi_station.OnConnect([this](const std::string& ssid) {
        std::string s = Lang::Strings::CONNECT_TO; s += ssid;
        Board::GetInstance().GetDisplay()->ShowNotification(s.c_str(), 30000);
    });
    wifi_station.OnConnected([this](const std::string& ssid) {
        std::string s = Lang::Strings::CONNECTED_TO; s += ssid;
        Board::GetInstance().GetDisplay()->ShowNotification(s.c_str(), 30000);
    });
    
    // 🟢 2. 启动 Station
    wifi_station.Start();

    // 🟢 3. 【RAM 注入】读取密码并填入驱动
    Settings settings("wifi", true);
    std::string saved_ssid = settings.GetString("ssid");
    std::string saved_password = settings.GetString("password");

    if (!saved_ssid.empty()) {
        ESP_LOGI(TAG, "Injecting saved credentials into driver: %s", saved_ssid.c_str());
        
        wifi_config_t wifi_cfg;
        memset(&wifi_cfg, 0, sizeof(wifi_config_t));
        
        size_t ssid_len = saved_ssid.length() > 31 ? 31 : saved_ssid.length();
        size_t pass_len = saved_password.length() > 63 ? 63 : saved_password.length();
        memcpy(wifi_cfg.sta.ssid, saved_ssid.c_str(), ssid_len);
        memcpy(wifi_cfg.sta.password, saved_password.c_str(), pass_len);
        
        esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg);
        esp_wifi_connect();
        
        // 🟢 【关键修复】开启省电模式
        ESP_LOGI(TAG, "Enabling WiFi Power Save to allow Audio/BLE to run smoothly");
        esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
        
    } else {
        ESP_LOGW(TAG, "No backup credentials in Settings.");
    }

    // 4. 等待连接
    if (!wifi_station.WaitForConnected(15 * 1000)) {
        ESP_LOGW(TAG, "Connection timeout. Entering provisioning...");
        wifi_station.Stop();
        vTaskDelay(pdMS_TO_TICKS(500));
        wifi_config_mode_ = true;
        EnterWifiConfigMode();
        return;
    }
    
    // 🟢 双重保险
    esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
}

NetworkInterface* WifiBoard::GetNetwork() {
    static EspNetwork network;
    return &network;
}

const char* WifiBoard::GetNetworkStateIcon() {
    if (wifi_config_mode_) {
        return FONT_AWESOME_WIFI;
    }
    auto& wifi_station = WifiStation::GetInstance();
    if (!wifi_station.IsConnected()) {
        return FONT_AWESOME_WIFI_SLASH;
    }
    int8_t rssi = wifi_station.GetRssi();
    if (rssi >= -60) {
        return FONT_AWESOME_WIFI;
    } else if (rssi >= -70) {
        return FONT_AWESOME_WIFI_FAIR;
    } else {
        return FONT_AWESOME_WIFI_WEAK;
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

void WifiBoard::SetPowerSaveMode(bool enabled) {
    auto& wifi_station = WifiStation::GetInstance();
    wifi_station.SetPowerSaveMode(enabled);
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
        cJSON_AddNumberToObject(screen, "brightness", backlight->brightness());
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