#ifndef SETTINGS_H
#define SETTINGS_H

#include <cstdint>
#include <string>
#include <nvs_flash.h>

// Thin wrapper over NVS that NEVER aborts the device. A namespace that fails
// to open (e.g. name > 15 chars, NVS full, or partition errors) degrades to
// "reads return defaults, writes are reported as errors and skipped".
class Settings {
public:
    enum class ReadStatus : uint8_t {
        Ok = 0,
        NotFound,
        Error,
    };

    Settings(const std::string& ns, bool read_write = false);
    ~Settings();

    // True if nvs_open succeeded and the handle is valid for reads/writes.
    bool IsValid() const { return valid_; }
    // Read-only open of a namespace that does not exist yet.
    bool IsNotFound() const {
        return !valid_ && open_err_ == ESP_ERR_NVS_NOT_FOUND;
    }

    std::string GetString(const std::string& key, const std::string& default_value = "");
    int32_t GetInt(const std::string& key, int32_t default_value = 0);
    bool GetBool(const std::string& key, bool default_value = false);

    // Distinguishes missing keys from I/O errors. Existing Get*() still
    // return the default for both cases so other modules keep their behavior.
    ReadStatus TryGetString(const std::string& key, std::string* out);
    ReadStatus TryGetInt(const std::string& key, int32_t* out);
    ReadStatus TryGetBool(const std::string& key, bool* out);

    // Writes/erases return esp_err_t (ESP_OK on success). Callers may ignore the
    // return value; failures are already logged. dirty_ is only set on success.
    esp_err_t SetString(const std::string& key, const std::string& value);
    esp_err_t SetInt(const std::string& key, int32_t value);
    esp_err_t SetBool(const std::string& key, bool value);
    esp_err_t EraseKey(const std::string& key);
    esp_err_t EraseAll();
    esp_err_t Commit();

    // Serialized directories/rules can exceed NVS's 4000-byte string limit.
    // Keep legacy strings readable and use a blob only for larger JSON values.
    ReadStatus TryGetJson(const std::string& key, std::string* out) {
        auto result = TryGetString(key, out);
        if (result != ReadStatus::Error || !valid_) return result;
        size_t length = 0;
        if (nvs_get_blob(nvs_handle_, key.c_str(), nullptr, &length) != ESP_OK || length > 65536) return ReadStatus::Error;
        std::string value(length, '\0');
        if (nvs_get_blob(nvs_handle_, key.c_str(), value.data(), &length) != ESP_OK) return ReadStatus::Error;
        if (out) *out = std::move(value);
        return ReadStatus::Ok;
    }
    std::string GetJson(const std::string& key, const std::string& fallback = "") {
        std::string value; return TryGetJson(key, &value) == ReadStatus::Ok ? value : fallback;
    }
    esp_err_t SetJson(const std::string& key, const std::string& value) {
        if (value.size() < 3900) return SetString(key, value);
        if (!valid_ || !read_write_ || value.size() > 65536) return ESP_FAIL;
        auto result = nvs_set_blob(nvs_handle_, key.c_str(), value.data(), value.size());
        if (result == ESP_OK) dirty_ = true;
        return result;
    }

private:
    std::string ns_;
    nvs_handle_t nvs_handle_ = 0;
    bool read_write_ = false;
    bool dirty_ = false;
    bool valid_ = false;
    esp_err_t open_err_ = ESP_FAIL;
};

#endif
