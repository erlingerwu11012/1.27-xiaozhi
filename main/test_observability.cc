#include "test_observability.h"

#include <esp_log.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/portmacro.h>
#include <sdkconfig.h>

#include <inttypes.h>

namespace {
constexpr const char* kTag = "TEST_TRACE";
constexpr int64_t kRepeatWindowUs = 5LL * 1000 * 1000;

struct RecentEvent {
    uint32_t key = 0;
    int64_t emitted_at_us = 0;
};

RecentEvent g_recent_events[16];
portMUX_TYPE g_recent_events_lock = portMUX_INITIALIZER_UNLOCKED;

uint32_t HashText(uint32_t hash, const char* text) {
    constexpr uint32_t kFnvPrime = 16777619u;
    if (!text) return hash;
    while (*text) {
        hash ^= static_cast<uint8_t>(*text++);
        hash *= kFnvPrime;
    }
    return hash;
}

bool ShouldEmit(const char* domain, const char* event,
                const uint32_t presence_generation, const char* outcome,
                const char* reason, const int value) {
    uint32_t key = 2166136261u;
    key = HashText(key, domain);
    key = HashText(key, event);
    key = HashText(key, outcome);
    key = HashText(key, reason);
    key ^= presence_generation;
    key *= 16777619u;
    key ^= static_cast<uint32_t>(value);
    const int64_t now_us = esp_timer_get_time();
    const size_t start = key % (sizeof(g_recent_events) / sizeof(g_recent_events[0]));

    bool emit = true;
    portENTER_CRITICAL(&g_recent_events_lock);
    for (size_t offset = 0; offset < sizeof(g_recent_events) / sizeof(g_recent_events[0]);
         ++offset) {
        RecentEvent& slot = g_recent_events[(start + offset) %
                                             (sizeof(g_recent_events) / sizeof(g_recent_events[0]))];
        if (slot.key == key) {
            emit = now_us - slot.emitted_at_us >= kRepeatWindowUs;
            if (emit) slot.emitted_at_us = now_us;
            portEXIT_CRITICAL(&g_recent_events_lock);
            return emit;
        }
        if (slot.key == 0) {
            slot = {key, now_us};
            portEXIT_CRITICAL(&g_recent_events_lock);
            return true;
        }
    }
    g_recent_events[start] = {key, now_us};
    portEXIT_CRITICAL(&g_recent_events_lock);
    return true;
}
}

namespace test_observability {

void Event(const char* domain, const char* event,
           const uint32_t presence_generation, const char* outcome,
           const char* reason, const int value) {
#if defined(CONFIG_TEMPORARY_TEST_OBSERVABILITY) && \
    CONFIG_TEMPORARY_TEST_OBSERVABILITY
    if (!ShouldEmit(domain, event, presence_generation, outcome, reason, value)) {
        return;
    }
    ESP_LOGI(kTag,
             "domain=%s event=%s gen=%" PRIu32 " outcome=%s reason=%s value=%d",
             domain ? domain : "-", event ? event : "-", presence_generation,
             outcome ? outcome : "-", reason ? reason : "-", value);
#else
    (void)domain;
    (void)event;
    (void)presence_generation;
    (void)outcome;
    (void)reason;
    (void)value;
#endif
}

}  // namespace test_observability
