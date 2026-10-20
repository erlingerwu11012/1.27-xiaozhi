#include "ota_tls_diag.h"

#include <atomic>
#include <cstring>
#include <cerrno>

#include <sdkconfig.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <esp_log.h>
#include <esp_timer.h>
#include <esp_heap_caps.h>
#include <esp_crt_bundle.h>
#include <esp_tls.h>
#include <wifi_station.h>

#define TAG "OtaTlsDiag"

namespace OtaTlsDiag {
namespace {

std::atomic<uint32_t> g_next_attempt{1};
std::atomic<uint32_t> g_active_attempt{0};
std::atomic<uint32_t> g_wifi_generation{0};
std::atomic<int64_t> g_got_ip_us{0};

SemaphoreHandle_t Mutex() {
    static StaticSemaphore_t storage;
    static SemaphoreHandle_t handle = xSemaphoreCreateMutexStatic(&storage);
    return handle;
}

#if CONFIG_REALECHO_OTA_TLS_DIAG
void LogTaskMeta(uint32_t attempt_id, const char* stage) {
    TaskHandle_t task = xTaskGetCurrentTaskHandle();
    const char* name = pcTaskGetName(task);
    const UBaseType_t hwm_words = uxTaskGetStackHighWaterMark(task);
    const size_t hwm_bytes =
        static_cast<size_t>(hwm_words) * sizeof(StackType_t);
    ESP_LOGI(TAG, "[OTA_TLS] event=task attempt=%u stage=%s task=%s stack_hwm_bytes=%u",
             static_cast<unsigned>(attempt_id), stage, name ? name : "?",
             static_cast<unsigned>(hwm_bytes));
}
#endif

}  // namespace

uint32_t BeginAttempt(const char* owner) {
    SemaphoreHandle_t mu = Mutex();
    if (xSemaphoreTake(mu, pdMS_TO_TICKS(1)) != pdTRUE) {
        ESP_LOGW(TAG, "[OTA_TLS] event=busy owner=%s active=%u",
                 owner ? owner : "?", static_cast<unsigned>(g_active_attempt.load()));
        return 0;
    }
    if (g_active_attempt.load() != 0) {
        xSemaphoreGive(mu);
        ESP_LOGW(TAG, "[OTA_TLS] event=overlap_rejected owner=%s active=%u",
                 owner ? owner : "?", static_cast<unsigned>(g_active_attempt.load()));
        return 0;
    }
    uint32_t id = g_next_attempt.fetch_add(1);
    if (id == 0) {
        id = g_next_attempt.fetch_add(1);
    }
    g_active_attempt.store(id);
    xSemaphoreGive(mu);
#if CONFIG_REALECHO_OTA_TLS_DIAG
    ESP_LOGI(TAG, "[OTA_TLS] event=attempt_begin attempt=%u owner=%s",
             static_cast<unsigned>(id), owner ? owner : "?");
    LogHeapWifi(id, "begin");
    LogTaskMeta(id, "begin");
#else
    (void)owner;
#endif
    return id;
}

void EndAttempt(uint32_t attempt_id) {
    if (attempt_id == 0) {
        return;
    }
    SemaphoreHandle_t mu = Mutex();
    if (xSemaphoreTake(mu, pdMS_TO_TICKS(1000)) != pdTRUE) {
        return;
    }
    if (g_active_attempt.load() == attempt_id) {
        g_active_attempt.store(0);
#if CONFIG_REALECHO_OTA_TLS_DIAG
        ESP_LOGI(TAG, "[OTA_TLS] event=attempt_end attempt=%u", static_cast<unsigned>(attempt_id));
#endif
    } else {
#if CONFIG_REALECHO_OTA_TLS_DIAG
        ESP_LOGW(TAG, "[OTA_TLS] event=stale_end attempt=%u active=%u",
                 static_cast<unsigned>(attempt_id),
                 static_cast<unsigned>(g_active_attempt.load()));
#endif
    }
    xSemaphoreGive(mu);
}

bool IsBusy() {
    return g_active_attempt.load() != 0;
}

uint32_t ActiveAttemptId() {
    return g_active_attempt.load();
}

void NoteWifiGotIp() {
    g_got_ip_us.store(esp_timer_get_time());
    g_wifi_generation.fetch_add(1);
#if CONFIG_REALECHO_OTA_TLS_DIAG
    ESP_LOGI(TAG, "[OTA_TLS] event=wifi_got_ip generation=%u",
             static_cast<unsigned>(g_wifi_generation.load()));
#endif
}

uint32_t WifiGeneration() {
    return g_wifi_generation.load();
}

int64_t MsSinceGotIp() {
    int64_t t0 = g_got_ip_us.load();
    if (t0 <= 0) {
        return -1;
    }
    return (esp_timer_get_time() - t0) / 1000;
}

void LogStage(uint32_t attempt_id, const char* stage) {
#if CONFIG_REALECHO_OTA_TLS_DIAG
    ESP_LOGI(TAG, "[OTA_TLS] event=stage attempt=%u stage=%s",
             static_cast<unsigned>(attempt_id), stage ? stage : "?");
#else
    (void)attempt_id;
    (void)stage;
#endif
}

void LogHeapWifi(uint32_t attempt_id, const char* stage) {
#if CONFIG_REALECHO_OTA_TLS_DIAG
    size_t sram = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    size_t sram_largest = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
    size_t psram = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    int rssi = 0;
    auto& wifi = WifiStation::GetInstance();
    if (wifi.IsConnected()) {
        rssi = wifi.GetRssi();
    }
    ESP_LOGI(TAG,
             "[OTA_TLS] event=resources attempt=%u stage=%s sram=%u sram_largest=%u psram=%u "
             "rssi=%d wifi_gen=%u since_ip_ms=%lld",
             static_cast<unsigned>(attempt_id), stage ? stage : "?",
             static_cast<unsigned>(sram), static_cast<unsigned>(sram_largest),
             static_cast<unsigned>(psram), rssi,
             static_cast<unsigned>(WifiGeneration()),
             static_cast<long long>(MsSinceGotIp()));
#else
    (void)attempt_id;
    (void)stage;
#endif
}

void LogClose(uint32_t attempt_id, const char* source) {
#if CONFIG_REALECHO_OTA_TLS_DIAG
    ESP_LOGI(TAG, "[OTA_TLS] event=close attempt=%u source=%s active=%u",
             static_cast<unsigned>(attempt_id), source ? source : "?",
             static_cast<unsigned>(ActiveAttemptId()));
#else
    (void)attempt_id;
    (void)source;
#endif
}

void LogTlsError(uint32_t attempt_id, esp_err_t open_err, esp_err_t esp_tls_err,
                 int mbedtls_err, int tls_flags, int err_no) {
#if CONFIG_REALECHO_OTA_TLS_DIAG
    ESP_LOGW(TAG,
             "[OTA_TLS] event=tls_error attempt=%u open_err=0x%x esp_tls_err=0x%x "
             "mbedtls_err=0x%x tls_flags=0x%x errno=%d",
             static_cast<unsigned>(attempt_id), static_cast<unsigned>(open_err),
             static_cast<unsigned>(esp_tls_err), static_cast<unsigned>(mbedtls_err),
             static_cast<unsigned>(tls_flags), err_no);
#else
    (void)attempt_id;
    (void)open_err;
    (void)esp_tls_err;
    (void)mbedtls_err;
    (void)tls_flags;
    (void)err_no;
#endif
}

bool RunPureTlsProbe(uint32_t attempt_id) {
#if !CONFIG_REALECHO_OTA_TLS_PROBE
    (void)attempt_id;
    return false;
#else
    LogStage(attempt_id, "pure_tls_begin");
    LogHeapWifi(attempt_id, "pure_tls_begin");

    esp_tls_t* tls = esp_tls_init();
    if (tls == nullptr) {
        LogStage(attempt_id, "pure_tls_init_fail");
        return false;
    }

    esp_tls_cfg_t cfg = {};
    cfg.crt_bundle_attach = esp_crt_bundle_attach;
    cfg.timeout_ms = 30000;

    const char* host = "api.realecho.cn";
    int ret = esp_tls_conn_new_sync(host, strlen(host), 443, &cfg, tls);
    bool ok = (ret == 1);
    if (!ok) {
        int mbedtls_err = 0;
        int tls_flags = 0;
        esp_tls_error_handle_t err_handle = nullptr;
        esp_err_t gh = esp_tls_get_error_handle(tls, &err_handle);
        esp_err_t esp_tls_err = ESP_FAIL;
        if (gh == ESP_OK && err_handle != nullptr) {
            esp_tls_err = esp_tls_get_and_clear_last_error(err_handle, &mbedtls_err, &tls_flags);
        }
        LogTlsError(attempt_id, ESP_FAIL, esp_tls_err, mbedtls_err, tls_flags, errno);
        LogStage(attempt_id, "pure_tls_fail");
    } else {
        LogStage(attempt_id, "pure_tls_ok");
    }

    esp_tls_conn_destroy(tls);
    LogClose(attempt_id, "pure_tls_probe");
    LogHeapWifi(attempt_id, "pure_tls_end");
    return ok;
#endif
}

}  // namespace OtaTlsDiag
