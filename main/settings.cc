#include "settings.h"

#include <esp_err.h>
#include <esp_log.h>
#include <nvs_flash.h>

#define TAG "Settings"

Settings::Settings(const std::string& ns, bool read_write) : ns_(ns), read_write_(read_write) {
    open_err_ = nvs_open(ns.c_str(), read_write_ ? NVS_READWRITE : NVS_READONLY, &nvs_handle_);
    if (open_err_ == ESP_OK) {
        valid_ = true;
    } else {
        nvs_handle_ = 0;
        valid_ = false;
        // A read-only open of a not-yet-created namespace is an expected,
        // non-fatal "no data" result, not a configuration error.
        if (!read_write_ && open_err_ == ESP_ERR_NVS_NOT_FOUND) {
            ESP_LOGV(TAG, "NVS namespace '%s' not found (read-only, treating as empty)",
                     ns_.c_str());
        } else {
            ESP_LOGW(TAG, "NVS open failed ns=%s mode=%s err=0x%x (%s)",
                     ns_.c_str(), read_write_ ? "rw" : "ro",
                     static_cast<int>(open_err_), esp_err_to_name(open_err_));
        }
    }
}

Settings::~Settings() {
    if (!valid_ || nvs_handle_ == 0) {
        return;
    }
    if (read_write_ && dirty_) {
        const esp_err_t err = nvs_commit(nvs_handle_);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "NVS commit failed ns=%s err=0x%x (%s)",
                     ns_.c_str(), static_cast<int>(err), esp_err_to_name(err));
        }
    }
    nvs_close(nvs_handle_);
    nvs_handle_ = 0;
}

esp_err_t Settings::Commit() {
    if (!valid_ || !read_write_) return ESP_ERR_NVS_READ_ONLY;
    const esp_err_t result = nvs_commit(nvs_handle_);
    // An explicit failed commit must not be retried implicitly by the
    // destructor after the caller has already rolled back and reported failure.
    dirty_ = false;
    return result;
}

Settings::ReadStatus Settings::TryGetString(const std::string& key, std::string* out) {
    if (out != nullptr) {
        out->clear();
    }
    if (!valid_) {
        return IsNotFound() ? ReadStatus::NotFound : ReadStatus::Error;
    }

    size_t length = 0;
    const esp_err_t peek = nvs_get_str(nvs_handle_, key.c_str(), nullptr, &length);
    if (peek == ESP_ERR_NVS_NOT_FOUND) {
        return ReadStatus::NotFound;
    }
    if (peek != ESP_OK) {
        return ReadStatus::Error;
    }

    std::string value;
    value.resize(length);
    const esp_err_t err = nvs_get_str(nvs_handle_, key.c_str(), value.data(), &length);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        return ReadStatus::NotFound;
    }
    if (err != ESP_OK) {
        return ReadStatus::Error;
    }
    while (!value.empty() && value.back() == '\0') {
        value.pop_back();
    }
    if (out != nullptr) {
        *out = std::move(value);
    }
    return ReadStatus::Ok;
}

std::string Settings::GetString(const std::string& key, const std::string& default_value) {
    std::string value;
    if (TryGetString(key, &value) != ReadStatus::Ok) {
        return default_value;
    }
    return value;
}

esp_err_t Settings::SetString(const std::string& key, const std::string& value) {
    if (!read_write_) {
        ESP_LOGW(TAG, "Namespace %s is not open for writing", ns_.c_str());
        return ESP_ERR_NVS_READ_ONLY;
    }
    if (!valid_) {
        ESP_LOGW(TAG, "NVS namespace %s invalid, skip SetString(%s)", ns_.c_str(), key.c_str());
        return open_err_;
    }
    const esp_err_t err = nvs_set_str(nvs_handle_, key.c_str(), value.c_str());
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "nvs_set_str failed ns=%s key=%s err=0x%x (%s)",
                 ns_.c_str(), key.c_str(), static_cast<int>(err), esp_err_to_name(err));
        return err;
    }
    dirty_ = true;
    return ESP_OK;
}

Settings::ReadStatus Settings::TryGetInt(const std::string& key, int32_t* out) {
    if (!valid_) {
        return IsNotFound() ? ReadStatus::NotFound : ReadStatus::Error;
    }
    int32_t value = 0;
    const esp_err_t err = nvs_get_i32(nvs_handle_, key.c_str(), &value);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        return ReadStatus::NotFound;
    }
    if (err != ESP_OK) {
        return ReadStatus::Error;
    }
    if (out != nullptr) {
        *out = value;
    }
    return ReadStatus::Ok;
}

int32_t Settings::GetInt(const std::string& key, int32_t default_value) {
    int32_t value = 0;
    if (TryGetInt(key, &value) != ReadStatus::Ok) {
        return default_value;
    }
    return value;
}

esp_err_t Settings::SetInt(const std::string& key, int32_t value) {
    if (!read_write_) {
        ESP_LOGW(TAG, "Namespace %s is not open for writing", ns_.c_str());
        return ESP_ERR_NVS_READ_ONLY;
    }
    if (!valid_) {
        ESP_LOGW(TAG, "NVS namespace %s invalid, skip SetInt(%s)", ns_.c_str(), key.c_str());
        return open_err_;
    }
    const esp_err_t err = nvs_set_i32(nvs_handle_, key.c_str(), value);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "nvs_set_i32 failed ns=%s key=%s err=0x%x (%s)",
                 ns_.c_str(), key.c_str(), static_cast<int>(err), esp_err_to_name(err));
        return err;
    }
    dirty_ = true;
    return ESP_OK;
}

Settings::ReadStatus Settings::TryGetBool(const std::string& key, bool* out) {
    if (!valid_) {
        return IsNotFound() ? ReadStatus::NotFound : ReadStatus::Error;
    }
    uint8_t value = 0;
    const esp_err_t err = nvs_get_u8(nvs_handle_, key.c_str(), &value);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        return ReadStatus::NotFound;
    }
    if (err != ESP_OK) {
        return ReadStatus::Error;
    }
    if (out != nullptr) {
        *out = value != 0;
    }
    return ReadStatus::Ok;
}

bool Settings::GetBool(const std::string& key, bool default_value) {
    bool value = false;
    if (TryGetBool(key, &value) != ReadStatus::Ok) {
        return default_value;
    }
    return value;
}

esp_err_t Settings::SetBool(const std::string& key, bool value) {
    if (!read_write_) {
        ESP_LOGW(TAG, "Namespace %s is not open for writing", ns_.c_str());
        return ESP_ERR_NVS_READ_ONLY;
    }
    if (!valid_) {
        ESP_LOGW(TAG, "NVS namespace %s invalid, skip SetBool(%s)", ns_.c_str(), key.c_str());
        return open_err_;
    }
    const esp_err_t err = nvs_set_u8(nvs_handle_, key.c_str(), value ? 1 : 0);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "nvs_set_u8 failed ns=%s key=%s err=0x%x (%s)",
                 ns_.c_str(), key.c_str(), static_cast<int>(err), esp_err_to_name(err));
        return err;
    }
    dirty_ = true;
    return ESP_OK;
}

esp_err_t Settings::EraseKey(const std::string& key) {
    if (!read_write_) {
        ESP_LOGW(TAG, "Namespace %s is not open for writing", ns_.c_str());
        return ESP_ERR_NVS_READ_ONLY;
    }
    if (!valid_) {
        ESP_LOGW(TAG, "NVS namespace %s invalid, skip EraseKey(%s)", ns_.c_str(), key.c_str());
        return open_err_;
    }
    const esp_err_t err = nvs_erase_key(nvs_handle_, key.c_str());
    if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND) {
        ESP_LOGW(TAG, "nvs_erase_key failed ns=%s key=%s err=0x%x (%s)",
                 ns_.c_str(), key.c_str(), static_cast<int>(err), esp_err_to_name(err));
        return err;
    }
    return ESP_OK;
}

esp_err_t Settings::EraseAll() {
    if (!read_write_) {
        ESP_LOGW(TAG, "Namespace %s is not open for writing", ns_.c_str());
        return ESP_ERR_NVS_READ_ONLY;
    }
    if (!valid_) {
        ESP_LOGW(TAG, "NVS namespace %s invalid, skip EraseAll", ns_.c_str());
        return open_err_;
    }
    const esp_err_t err = nvs_erase_all(nvs_handle_);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "nvs_erase_all failed ns=%s err=0x%x (%s)",
                 ns_.c_str(), static_cast<int>(err), esp_err_to_name(err));
        return err;
    }
    return ESP_OK;
}
