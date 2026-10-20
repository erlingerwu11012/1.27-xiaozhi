#pragma once
#include "esp_err.h"
struct esp_vfs_spiffs_conf_t {
    const char* base_path;
    const char* partition_label;
    size_t max_files;
    bool format_if_mount_failed;
};
constexpr esp_err_t ESP_ERR_INVALID_STATE = 0x103;
inline esp_err_t esp_spiffs_register(const esp_vfs_spiffs_conf_t*) {return ESP_OK;}
inline esp_err_t esp_vfs_spiffs_register(const esp_vfs_spiffs_conf_t* conf) {return esp_spiffs_register(conf);}
