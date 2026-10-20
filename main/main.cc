#include <cstdio>
#include <esp_log.h>
#include <esp_err.h>
#include <esp_heap_caps.h>
#include <esp_system.h>
#include <nvs.h>
#include <nvs_flash.h>
#include <esp_event.h>

#include "application.h"
#include "system_info.h"

#define TAG "main"

extern "C" void app_main(void)
{
    ESP_LOGI(TAG, "[BOOT] reset_reason=%d",
             static_cast<int>(esp_reset_reason()));

    // --- PSRAM memory status check (debug) ---
    printf("--- Memory Status Check ---\n");
    printf("Internal SRAM free: %lu KB\n", (unsigned long)(heap_caps_get_free_size(MALLOC_CAP_INTERNAL) / 1024));
    printf("External PSRAM free: %lu KB\n", (unsigned long)(heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024));
    printf("Largest PSRAM block: %lu KB\n", (unsigned long)(heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM) / 1024));
    if (heap_caps_get_free_size(MALLOC_CAP_SPIRAM) == 0) {
        printf("WARNING: PSRAM not added to heap allocator!\n");
    }
    printf("---------------------------\n");

    // Initialize the default event loop
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    // Initialize NVS flash for WiFi configuration
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "Erasing NVS flash to fix corruption");
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    // Launch the application
    auto& app = Application::GetInstance();
    app.Start();
}
