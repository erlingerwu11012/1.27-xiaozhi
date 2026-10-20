#pragma once
#include <cstdio>
#define ESP_LOGI(tag, fmt, ...)                                                                    \
    do {                                                                                           \
    } while (0)
#define ESP_LOGW(tag, fmt, ...)                                                                    \
    do {                                                                                           \
        std::fprintf(stderr, "WARN " fmt "\n", ##__VA_ARGS__);                                     \
    } while (0)
#define ESP_LOGE(tag, fmt, ...)                                                                    \
    do {                                                                                           \
        std::fprintf(stderr, "ERROR " fmt "\n", ##__VA_ARGS__);                                    \
    } while (0)
