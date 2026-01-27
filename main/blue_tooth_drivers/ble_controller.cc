#include "ble_controller.h"
#include <esp_log.h>
#include <esp_system.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <nvs_flash.h>
#include <cstring>

// === 蓝牙底层头文件 ===
#include <esp_bt.h> 
#include "esp_nimble_hci.h"

// === NimBLE Host 专用头文件 ===
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

// === ESP HID 抽象层 ===
#include "esp_hidd.h"

#define TAG "BleController"

// 静态变量
static bool s_is_connected = false;
static esp_hidd_dev_t *s_hid_dev = NULL;

BleController& BleController::GetInstance() {
    static BleController instance;
    return instance;
}

// ---------------------------------------------------------
// 1. 完整的 HID 报告描述符 (键盘 + 媒体键)
// ---------------------------------------------------------
static const uint8_t hid_report_map_data[] = {
    // Keyboard (Report ID 1)
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x85, 0x01, 0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00, 
    0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02, 0x95, 0x01, 0x75, 0x08, 0x81, 0x01, 0x95, 0x06, 
    0x75, 0x08, 0x15, 0x00, 0x25, 0x65, 0x05, 0x07, 0x19, 0x00, 0x29, 0x65, 0x81, 0x00, 0xC0, 
    // Consumer Control (Media Keys, Report ID 2)
    0x05, 0x0C, 0x09, 0x01, 0xA1, 0x01, 0x85, 0x02, 0x09, 0xE9, 0x09, 0xEA, 0x09, 0xE2, 0x09, 0xCD, 
    0x09, 0xB5, 0x09, 0xB6, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x06, 0x81, 0x02, 0x95, 0x01, 
    0x75, 0x02, 0x81, 0x03, 0xC0
};

static esp_hid_raw_report_map_t report_maps[] = {
    {
        .data = hid_report_map_data,
        .len = sizeof(hid_report_map_data)
    }
};

// ---------------------------------------------------------
// 2. 广播与任务管理
// ---------------------------------------------------------

static void start_advertising() {
    struct ble_gap_adv_params adv_params;
    struct ble_hs_adv_fields fields;
    const char *name = "Xiaozhi_AI_Remote";
    int rc;

    memset(&fields, 0, sizeof fields);
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.name = (uint8_t *)name;
    fields.name_len = strlen(name);
    fields.name_is_complete = 1;
    fields.appearance = 0x03C1; // Keyboard appearance图标

    rc = ble_gap_adv_set_fields(&fields);
    if (rc != 0) {
        ESP_LOGE(TAG, "Error setting adv fields; rc=%d", rc);
        return;
    }

    memset(&adv_params, 0, sizeof adv_params);
    adv_params.conn_mode = BLE_GAP_CONN_MODE_UND;
    adv_params.disc_mode = BLE_GAP_DISC_MODE_GEN;

    rc = ble_gap_adv_start(0, NULL, BLE_HS_FOREVER, &adv_params, NULL, NULL);
    if (rc != 0) {
        ESP_LOGE(TAG, "Error enabling advertisement; rc=%d", rc);
    } else {
        ESP_LOGI(TAG, "Advertising started...");
    }
}

static void nimble_host_task(void *param) {
    ESP_LOGI(TAG, "BLE Host Task Started");
    nimble_port_run();
    nimble_port_freertos_deinit();
}

static void ble_on_sync(void) {
    int rc = ble_hs_util_ensure_addr(0);
    if (rc != 0) {
        ESP_LOGE(TAG, "Error loading address; rc=%d", rc);
        return;
    }
    start_advertising();
}

static void hidd_event_callback(void *handler_args, esp_event_base_t base, int32_t id, void *event_data) {
    esp_hidd_event_t event = (esp_hidd_event_t)id;
    switch (event) {
    case ESP_HIDD_START_EVENT:
        ESP_LOGI(TAG, "HID Service Started");
        break;
    case ESP_HIDD_CONNECT_EVENT:
        ESP_LOGI(TAG, "HID CONNECTED");
        s_is_connected = true;
        break;
    case ESP_HIDD_DISCONNECT_EVENT:
        ESP_LOGI(TAG, "HID DISCONNECTED");
        s_is_connected = false;
        start_advertising(); // 断开后重新开始广播
        break;
    default:
        break;
    }
}

// ---------------------------------------------------------
// 3. 核心初始化 (支持 Coex 259 兼容模式)
// ---------------------------------------------------------

void BleController::Init() {
    esp_err_t ret;

    // A. NVS 初始化 (蓝牙分区必须)
    ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    ESP_LOGI(TAG, "Initializing BLE with Advanced Coex Handling...");

    // B. Controller 初始化
    esp_bt_controller_config_t bt_cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    ret = esp_bt_controller_init(&bt_cfg);
    if (ret != ESP_OK && ret != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "Controller Init Failed: 0x%x. ABORTING.", ret);
        return; // 🛑 严格拦截
    }

    // C. Controller 启用
    ret = esp_bt_controller_enable(ESP_BT_MODE_BLE);
    if (ret != ESP_OK && ret != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "Controller Enable Failed: 0x%x. ABORTING.", ret);
        return; // 🛑 严格拦截
    }

    // D. HCI 初始化
    ret = esp_nimble_hci_init();
    if (ret != ESP_OK && ret != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "HCI Init Failed: 0x%x. ABORTING.", ret);
        return; // 🛑 严格拦截
    }

    // E. Host 强制重置 (清洗软件栈数据，解决 LoadProhibited 核心逻辑)
    // 如果系统之前不小心启动了 NimBLE，先把它关干净
    nimble_port_stop();
    nimble_port_deinit();
    
    vTaskDelay(pdMS_TO_TICKS(50)); // 给协议栈喘息时间

    ret = nimble_port_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "NimBLE Port Init Failed: %d. ABORTING.", ret);
        return;
    }

    // 设置同步回调
    ble_hs_cfg.sync_cb = ble_on_sync;

    // F. 注册 HID 设备 (GATT 服务)
    ESP_LOGI(TAG, "Registering HID Device...");
    esp_hid_device_config_t hidd_config = {
        .vendor_id = 0x16C0,
        .product_id = 0x05DF,
        .version = 0x0100,
        .device_name = (char*)"Xiaozhi_AI_Remote",
        .manufacturer_name = (char*)"Xiaozhi",
        .serial_number = (char*)"1234567890",
        .report_maps = report_maps,
        .report_maps_len = 1,
    };

    ret = esp_hidd_dev_init(&hidd_config, ESP_HID_TRANSPORT_BLE, hidd_event_callback, &s_hid_dev);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "HID Device Init Failed: 0x%x. ABORTING.", ret);
        return; // 🛑 如果这里失败，后面启动任务必崩，所以必须拦截
    }

    // G. 启动任务
    nimble_port_freertos_init(nimble_host_task);
    ESP_LOGI(TAG, "BleController Initialized Successfully.");
}

// ---------------------------------------------------------
// 4. 功能实现
// ---------------------------------------------------------

bool BleController::IsConnected() {
    return s_is_connected;
}

void BleController::SendKey(uint8_t key_code, uint8_t modifier) {
    if (!s_is_connected || !s_hid_dev) return;
    
    // 键盘报表 ID 1, 长度 8 字节
    uint8_t buffer[8] = {modifier, 0, key_code, 0, 0, 0, 0, 0};
    esp_hidd_dev_input_set(s_hid_dev, 0, 1, buffer, 8);
    
    // 按键抬起
    uint8_t empty[8] = {0, 0, 0, 0, 0, 0, 0, 0};
    esp_hidd_dev_input_set(s_hid_dev, 0, 1, empty, 8);
}

void BleController::LockScreen() {
    ESP_LOGI(TAG, "Executing: Lock Screen (Win+L)");
    SendKey(0x0F, 0x08); // L 是 0x0F, Win 是 0x08
}

static void SendMediaKey(uint8_t mask) {
    if (!s_is_connected || !s_hid_dev) return;
    
    // 媒体键报表 ID 2, 长度 1 字节
    uint8_t buffer[1] = {mask};
    esp_hidd_dev_input_set(s_hid_dev, 0, 2, buffer, 1);
    
    // 抬起
    buffer[0] = 0;
    esp_hidd_dev_input_set(s_hid_dev, 0, 2, buffer, 1);
}

void BleController::VolumeUp()   { ESP_LOGI(TAG, "Media: Volume Up");   SendMediaKey(0x01); }
void BleController::VolumeDown() { ESP_LOGI(TAG, "Media: Volume Down"); SendMediaKey(0x02); }
void BleController::Mute()       { ESP_LOGI(TAG, "Media: Mute");        SendMediaKey(0x04); }
void BleController::PlayPause()  { ESP_LOGI(TAG, "Media: Play/Pause");  SendMediaKey(0x08); }
void BleController::NextTrack()  { ESP_LOGI(TAG, "Media: Next Track");  SendMediaKey(0x10); }
void BleController::PrevTrack()  { ESP_LOGI(TAG, "Media: Prev Track");  SendMediaKey(0x20); }

void BleController::MoveMouse(int8_t x, int8_t y) {
    // 预留接口，暂无逻辑
}