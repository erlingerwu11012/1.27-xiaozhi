#pragma once
#include "esp_timer.h"
inline uint32_t esp_cpu_get_cycle_count() {
    return static_cast<uint32_t>(esp_timer_get_time() * 240);
}
