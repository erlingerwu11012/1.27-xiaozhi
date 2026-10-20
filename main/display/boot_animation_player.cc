#include "boot_animation_player.h"

#include <cstring>
#include <memory>

#include <esp_heap_caps.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>


namespace {

constexpr const char* kTag = "BootAnimation";
constexpr uint8_t kMagic[] = {'R', 'E', 'B', 'A'};
constexpr uint16_t kVersion = 1;
constexpr size_t kHeaderSize = 32;
constexpr uint16_t kMaxFrames = 240;

uint16_t ReadLe16(const uint8_t* value) {
    return static_cast<uint16_t>(value[0]) |
           (static_cast<uint16_t>(value[1]) << 8);
}

uint32_t ReadLe32(const uint8_t* value) {
    return static_cast<uint32_t>(value[0]) |
           (static_cast<uint32_t>(value[1]) << 8) |
           (static_cast<uint32_t>(value[2]) << 16) |
           (static_cast<uint32_t>(value[3]) << 24);
}

struct Header {
    uint16_t width = 0;
    uint16_t height = 0;
    uint16_t crop_x = 0;
    uint16_t crop_y = 0;
    uint16_t crop_width = 0;
    uint16_t crop_height = 0;
    uint16_t frame_interval_ms = 0;
    uint16_t frame_count = 0;
    uint32_t duration_ms = 0;
    uint32_t payload_size = 0;
};

bool ParseHeader(const uint8_t* data,
                 size_t size,
                 int display_width,
                 int display_height,
                 Header& out) {
    if (data == nullptr || size < kHeaderSize ||
        std::memcmp(data, kMagic, sizeof(kMagic)) != 0) {
        ESP_LOGE(kTag, "Missing or invalid REBA header");
        return false;
    }
    const uint16_t version = ReadLe16(data + 4);
    const uint16_t header_size = ReadLe16(data + 6);
    if (version != kVersion || header_size != kHeaderSize) {
        ESP_LOGE(kTag, "Unsupported animation version=%u header=%u",
                 static_cast<unsigned>(version),
                 static_cast<unsigned>(header_size));
        return false;
    }

    out.width = ReadLe16(data + 8);
    out.height = ReadLe16(data + 10);
    out.crop_x = ReadLe16(data + 12);
    out.crop_y = ReadLe16(data + 14);
    out.crop_width = ReadLe16(data + 16);
    out.crop_height = ReadLe16(data + 18);
    out.frame_interval_ms = ReadLe16(data + 20);
    out.frame_count = ReadLe16(data + 22);
    out.duration_ms = ReadLe32(data + 24);
    out.payload_size = ReadLe32(data + 28);

    if (out.width != display_width || out.height != display_height ||
        out.width == 0 || out.height == 0 || out.crop_width == 0 ||
        out.crop_height == 0 ||
        static_cast<uint32_t>(out.crop_x) + out.crop_width > out.width ||
        static_cast<uint32_t>(out.crop_y) + out.crop_height > out.height ||
        out.frame_interval_ms < 10 || out.frame_interval_ms > 1000 ||
        out.frame_count == 0 || out.frame_count > kMaxFrames ||
        out.duration_ms !=
            static_cast<uint32_t>(out.frame_interval_ms) * out.frame_count ||
        out.payload_size != size - kHeaderSize) {
        ESP_LOGE(kTag,
                 "Invalid animation geometry/timing: canvas=%ux%u "
                 "crop=%u,%u %ux%u interval=%u frames=%u duration=%lu "
                 "payload=%lu/%u",
                 out.width, out.height, out.crop_x, out.crop_y,
                 out.crop_width, out.crop_height, out.frame_interval_ms,
                 out.frame_count, static_cast<unsigned long>(out.duration_ms),
                 static_cast<unsigned long>(out.payload_size),
                 static_cast<unsigned>(size - kHeaderSize));
        return false;
    }
    return true;
}

struct HeapCapsDeleter {
    void operator()(void* ptr) const {
        if (ptr != nullptr) heap_caps_free(ptr);
    }
};

}  // namespace


bool BootAnimationPlayer::Play(const void* raw_data,
                               size_t size,
                               int display_width,
                               int display_height,
                               FrameSubmitter submitter,
                               std::function<void()> on_started) {
    if (!submitter) return false;
    const auto* data = static_cast<const uint8_t*>(raw_data);
    Header header;
    if (!ParseHeader(data, size, display_width, display_height, header)) {
        return false;
    }

    const size_t framebuffer_pixels =
        static_cast<size_t>(header.width) * header.height;
    const size_t crop_pixels =
        static_cast<size_t>(header.crop_width) * header.crop_height;
    std::unique_ptr<uint16_t, HeapCapsDeleter> framebuffer(
        static_cast<uint16_t*>(heap_caps_calloc(
            framebuffer_pixels, sizeof(uint16_t),
            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)));
    std::unique_ptr<uint8_t, HeapCapsDeleter> grayscale(
        static_cast<uint8_t*>(heap_caps_calloc(
            crop_pixels, sizeof(uint8_t),
            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)));
    if (!framebuffer || !grayscale) {
        ESP_LOGE(kTag, "Unable to allocate animation buffers");
        return false;
    }

    if (!submitter(framebuffer.get(), header.width,
                   0, 0, header.width, header.height)) {
        ESP_LOGE(kTag, "Unable to commit startup black frame");
        return false;
    }
    if (on_started) on_started();

    const uint8_t* cursor = data + kHeaderSize;
    const uint8_t* end = data + size;
    TickType_t next_wake = xTaskGetTickCount();
    const TickType_t frame_ticks =
        pdMS_TO_TICKS(header.frame_interval_ms);

    ESP_LOGI(kTag,
             "Playing %u frames at %u ms, crop=%u,%u %ux%u, bytes=%u",
             header.frame_count, header.frame_interval_ms,
             header.crop_x, header.crop_y,
             header.crop_width, header.crop_height,
             static_cast<unsigned>(size));

    for (uint16_t frame = 0; frame < header.frame_count; ++frame) {
        if (static_cast<size_t>(end - cursor) < sizeof(uint32_t)) {
            ESP_LOGE(kTag, "Frame %u size is truncated", frame);
            return false;
        }
        const uint32_t encoded_size = ReadLe32(cursor);
        cursor += sizeof(uint32_t);
        if (encoded_size > static_cast<size_t>(end - cursor)) {
            ESP_LOGE(kTag, "Frame %u payload is truncated", frame);
            return false;
        }
        const uint8_t* frame_end = cursor + encoded_size;
        size_t pixel = 0;
        while (pixel < crop_pixels) {
            if (cursor >= frame_end) {
                ESP_LOGE(kTag, "Frame %u run stream ended early", frame);
                return false;
            }
            const uint8_t control = *cursor++;
            const size_t count = (control & 0x7FU) + 1U;
            if (pixel + count > crop_pixels) {
                ESP_LOGE(kTag, "Frame %u run exceeds crop", frame);
                return false;
            }
            if ((control & 0x80U) != 0) {
                if (count > static_cast<size_t>(frame_end - cursor)) {
                    ESP_LOGE(kTag, "Frame %u literal is truncated", frame);
                    return false;
                }
                for (size_t index = 0; index < count; ++index) {
                    grayscale.get()[pixel + index] ^= cursor[index];
                }
                cursor += count;
            }
            pixel += count;
        }
        if (cursor != frame_end) {
            ESP_LOGE(kTag, "Frame %u has trailing bytes", frame);
            return false;
        }

        for (uint16_t row = 0; row < header.crop_height; ++row) {
            auto* output = framebuffer.get() +
                static_cast<size_t>(header.crop_y + row) * header.width +
                header.crop_x;
            const auto* input = grayscale.get() +
                static_cast<size_t>(row) * header.crop_width;
            for (uint16_t column = 0;
                 column < header.crop_width;
                 ++column) {
                const uint16_t gray = input[column];
                output[column] = static_cast<uint16_t>(
                    ((gray >> 3) << 11) |
                    ((gray >> 2) << 5) |
                    (gray >> 3));
            }
        }

        if (!submitter(framebuffer.get(), header.width,
                       header.crop_x, header.crop_y,
                       header.crop_x + header.crop_width,
                       header.crop_y + header.crop_height)) {
            ESP_LOGE(kTag, "Frame %u LCD submission failed", frame);
            return false;
        }
        vTaskDelayUntil(&next_wake, frame_ticks);
    }

    if (cursor != end) {
        ESP_LOGE(kTag, "Animation contains trailing payload");
        return false;
    }
    ESP_LOGI(kTag, "Startup animation complete");
    return true;
}

