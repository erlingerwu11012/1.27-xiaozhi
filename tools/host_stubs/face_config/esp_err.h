#pragma once

#include <cstddef>
#include <cstdint>

using esp_err_t = int;

constexpr esp_err_t ESP_OK = 0;
constexpr esp_err_t ESP_FAIL = -1;
constexpr esp_err_t ESP_ERR_NO_MEM = 0x101;
constexpr esp_err_t ESP_ERR_INVALID_ARG = 0x102;
constexpr esp_err_t ESP_ERR_NVS_BASE = 0x1100;
constexpr esp_err_t ESP_ERR_NVS_NOT_FOUND = ESP_ERR_NVS_BASE + 0x02;
constexpr esp_err_t ESP_ERR_NVS_INVALID_HANDLE = ESP_ERR_NVS_BASE + 0x04;
constexpr esp_err_t ESP_ERR_NVS_INVALID_NAME = ESP_ERR_NVS_BASE + 0x05;
constexpr esp_err_t ESP_ERR_NVS_INVALID_LENGTH = ESP_ERR_NVS_BASE + 0x0b;
constexpr esp_err_t ESP_ERR_NVS_READ_ONLY = ESP_ERR_NVS_BASE + 0x0d;

inline const char* esp_err_to_name(esp_err_t err) {
    if (err == ESP_OK) return "ESP_OK";
    if (err == ESP_ERR_NVS_NOT_FOUND) return "ESP_ERR_NVS_NOT_FOUND";
    if (err == ESP_ERR_NVS_READ_ONLY) return "ESP_ERR_NVS_READ_ONLY";
    return "ESP_FAIL";
}
