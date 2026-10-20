#pragma once
#include <cstdint>
#include <mutex>
using BaseType_t = int;
using UBaseType_t = unsigned;
using TickType_t = uint32_t;
constexpr int pdTRUE = 1, pdFALSE = 0, pdPASS = 1, pdFAIL = 0;
constexpr TickType_t portMAX_DELAY = UINT32_MAX;
#define pdMS_TO_TICKS(ms) (static_cast<TickType_t>(ms))
#define portNUM_PROCESSORS 2
struct portMUX_TYPE {
    std::mutex mutex;
};
#define portMUX_INITIALIZER_UNLOCKED                                                               \
    {                                                                                              \
    }
#define portENTER_CRITICAL(m) ((m)->mutex.lock())
#define portEXIT_CRITICAL(m) ((m)->mutex.unlock())
