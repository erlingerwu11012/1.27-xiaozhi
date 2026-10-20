#include "sdkconfig.h"

#ifdef CONFIG_USE_USB_STREAM
#include <cstddef>
#include <atomic>
#include <esp_heap_caps.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace {
void* JpegPsramAllocate(size_t bytes, size_t alignment = 0) {
    constexpr unsigned caps = MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT;
    void* ptr = alignment ? heap_caps_aligned_calloc(alignment, 1, bytes, caps)
                          : heap_caps_calloc(1, bytes, caps);
    if (!ptr) {
        ESP_LOGE("CameraMemory", "[PHOTO_PSRAM] JPEG workspace failed bytes=%u task=%s; no internal fallback",
                 static_cast<unsigned>(bytes), pcTaskGetName(nullptr));
    } else if (bytes == 20480) {
        // One diagnostic confirms where the former 20 KiB SRAM attempt goes.
        static std::atomic<bool> reported{false};
        if (!reported.exchange(true)) {
            ESP_LOGI("CameraMemory", "[PHOTO_PSRAM] JPEG workspace bytes=20480 caps=0x404 task=%s",
                     pcTaskGetName(nullptr));
        }
    }
    return ptr;
}
}

// esp_new_jpeg is a prebuilt software codec. Wrap its allocation entry points
// in project code; jpeg_free / jpeg_free_align already use heap_caps_free.
// In particular, the RGB/YUV MCU workspaces otherwise try INTERNAL first.
extern "C" void* __wrap_jpeg_calloc(size_t bytes) { return JpegPsramAllocate(bytes); }
extern "C" void* __wrap_jpeg_calloc_inner(size_t bytes) { return JpegPsramAllocate(bytes); }
extern "C" void* __wrap_jpeg_calloc_align(size_t bytes, int alignment) {
    return JpegPsramAllocate(bytes, alignment);
}
extern "C" void* __wrap_jpeg_calloc_align_inner(size_t bytes, int alignment) {
    return JpegPsramAllocate(bytes, alignment);
}
#endif
