#include "wallpaper_ota.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <vector>

#include <esp_app_desc.h>
#include <esp_crt_bundle.h>
#include <esp_http_client.h>
#include <esp_log.h>
#include <esp_timer.h>
#include <mbedtls/sha256.h>
#include <nvs.h>

#include "application.h"
#include "board.h"
#include "mmap_asset_bundle.h"
#include "spine_ota.h"
#include "spine_ota_crypto.h"
#include "wallpaper_assets.h"

#define TAG "WallpaperOta"

namespace {

bool IsHexLowerSha256(const std::string& value) {
    if (value.size() != 64) return false;
    for (char c : value) {
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
    }
    return true;
}

bool IsAllowedId(const std::string& value) {
    if (value.empty() || value.size() > 64) return false;
    for (unsigned char c : value) {
        if (!(std::isalnum(c) || c == '_' || c == '-')) return false;
    }
    return true;
}

std::string ToLowerAscii(const std::string& value) {
    std::string out = value;
    for (char& c : out) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return out;
}

bool CommaListAllows(const std::string& value, const char* allow_list) {
    if (allow_list == nullptr || allow_list[0] == '\0') return false;
    std::string list(allow_list);
    size_t start = 0;
    while (start < list.size()) {
        size_t comma = list.find(',', start);
        std::string item = list.substr(start, comma == std::string::npos
                                              ? std::string::npos : comma - start);
        while (!item.empty() && (item.front() == ' ' || item.front() == '\t')) item.erase(item.begin());
        while (!item.empty() && (item.back() == ' ' || item.back() == '\t')) item.pop_back();
        if (item == "*" || ToLowerAscii(item) == ToLowerAscii(value)) return true;
        if (comma == std::string::npos) break;
        start = comma + 1;
    }
    return false;
}

std::vector<int> ParseVersionParts(const std::string& version) {
    std::vector<int> result;
    size_t start = 0;
    while (start < version.size()) {
        const size_t dot = version.find('.', start);
        const std::string part = version.substr(start, dot == std::string::npos
                                                        ? std::string::npos : dot - start);
        if (part.empty()) break;
        result.push_back(std::atoi(part.c_str()));
        if (dot == std::string::npos) break;
        start = dot + 1;
    }
    return result;
}

bool FirmwareMeetsMin(const std::string& current, const std::string& min_fw) {
    auto cur = ParseVersionParts(current);
    auto min = ParseVersionParts(min_fw);
    const size_t count = std::max(cur.size(), min.size());
    cur.resize(count, 0);
    min.resize(count, 0);
    for (size_t i = 0; i < count; ++i) {
        if (cur[i] != min[i]) return cur[i] > min[i];
    }
    return true;
}

}  // namespace

const char* WallpaperOtaErrorToString(WallpaperOtaError err) {
    switch (err) {
        case WallpaperOtaError::kNone: return "none";
        case WallpaperOtaError::kBusy: return "E_BUSY";
        case WallpaperOtaError::kUrlDenied: return "E_URL_DENIED";
        case WallpaperOtaError::kPackUnknown: return "E_PACK_UNKNOWN";
        case WallpaperOtaError::kSize: return "E_SIZE";
        case WallpaperOtaError::kSha: return "E_SHA256";
        case WallpaperOtaError::kSig: return "E_SIGNATURE";
        case WallpaperOtaError::kMinFw: return "E_MIN_FW";
        case WallpaperOtaError::kFlash: return "E_FLASH";
        case WallpaperOtaError::kNetwork: return "E_NETWORK";
        case WallpaperOtaError::kBundle: return "E_BUNDLE";
        case WallpaperOtaError::kNvs: return "E_NVS";
    }
    return "E_BUNDLE";
}

const char* WallpaperOtaPhaseToString(WallpaperOtaPhase phase) {
    switch (phase) {
        case WallpaperOtaPhase::kIdle: return "idle";
        case WallpaperOtaPhase::kWaiting: return "waiting";
        case WallpaperOtaPhase::kDownloading: return "downloading";
        case WallpaperOtaPhase::kVerifying: return "verifying";
        case WallpaperOtaPhase::kApplying: return "applying";
        case WallpaperOtaPhase::kSuccess: return "success";
        case WallpaperOtaPhase::kFailed: return "failed";
    }
    return "failed";
}

bool WallpaperOta::TryAcquire(WallpaperOtaStatusCallback cb) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (running_) return false;
    running_ = true;
    status_cb_ = std::move(cb);
    last_reported_progress_ = -1;
    last_report_us_ = 0;
    return true;
}

void WallpaperOta::Release() {
    std::lock_guard<std::mutex> lock(mutex_);
    running_ = false;
    status_cb_ = nullptr;
    last_reported_progress_ = -1;
    last_report_us_ = 0;
}

bool WallpaperOta::IsRunning() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return running_;
}

void WallpaperOta::Report(WallpaperOtaPhase phase, int progress,
                          WallpaperOtaError error, const std::string& task_id,
                          const std::string& pack_id) {
    WallpaperOtaStatusCallback callback;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        const int64_t now = esp_timer_get_time();
        if (phase == WallpaperOtaPhase::kDownloading && progress == last_reported_progress_ &&
            now - last_report_us_ < 500000) return;
        last_reported_progress_ = progress;
        last_report_us_ = now;
        callback = status_cb_;
    }
    if (callback) callback(phase, progress, error, task_id, pack_id);
}

bool WallpaperOta::ParseTask(const cJSON* root, WallpaperOtaTask& out,
                             WallpaperOtaError& error) {
    error = WallpaperOtaError::kBundle;
    out = {};
    if (!cJSON_IsObject(root)) return false;
    auto required_string = [&](const char* key, std::string& target, size_t max_len) {
        cJSON* value = cJSON_GetObjectItem(root, key);
        if (!cJSON_IsString(value) || value->valuestring == nullptr) return false;
        target = value->valuestring;
        return !target.empty() && target.size() <= max_len;
    };
    if (!required_string("task_id", out.task_id, 80) ||
        !required_string("pack_id", out.pack_id, 64) ||
        !required_string("version", out.version, 32) ||
        !required_string("sha256", out.sha256, 64) ||
        !required_string("signature", out.signature, 512) ||
        !required_string("url", out.url, 1024) ||
        !required_string("min_fw", out.min_fw, 32)) return false;
    cJSON* size = cJSON_GetObjectItem(root, "size");
    if (!cJSON_IsNumber(size) || size->valuedouble <= 0 ||
        size->valuedouble > static_cast<double>(kWallpaperOtaMaxBytes)) {
        error = WallpaperOtaError::kSize;
        return false;
    }
    out.size = static_cast<uint32_t>(size->valuedouble);
    if (!IsAllowedId(out.pack_id)) {
        error = WallpaperOtaError::kPackUnknown;
        return false;
    }
    if (!IsHexLowerSha256(out.sha256)) {
        error = WallpaperOtaError::kSha;
        return false;
    }
    error = WallpaperOtaError::kNone;
    return true;
}

WallpaperOtaError WallpaperOta::Precheck(const WallpaperOtaTask& task,
                                          std::string* detail) {
    if (task.size == 0 || task.size > kWallpaperOtaMaxBytes) {
        if (detail) *detail = "size";
        return WallpaperOtaError::kSize;
    }
    std::string host, path, signed_url;
    if (!SpineOtaParseHttpsUrl(task.url, host, path, signed_url)) {
        if (detail) *detail = "url";
        return WallpaperOtaError::kUrlDenied;
    }
#ifdef CONFIG_WALLPAPER_OTA_ALLOWED_HOSTS
    if (!CommaListAllows(host, CONFIG_WALLPAPER_OTA_ALLOWED_HOSTS)) {
#else
    if (true) {
#endif
        if (detail) *detail = "host";
        return WallpaperOtaError::kUrlDenied;
    }
#ifdef CONFIG_WALLPAPER_OTA_ALLOWED_PACK_IDS
    if (!CommaListAllows(task.pack_id, CONFIG_WALLPAPER_OTA_ALLOWED_PACK_IDS)) {
#else
    if (true) {
#endif
        if (detail) *detail = "pack";
        return WallpaperOtaError::kPackUnknown;
    }
    const auto* desc = esp_app_get_description();
    if (desc == nullptr || !FirmwareMeetsMin(desc->version, task.min_fw)) {
        if (detail) *detail = "min_fw";
        return WallpaperOtaError::kMinFw;
    }
    // Reuse the ES256 envelope while binding this signature to a wallpaper
    // domain literal. A signed role task cannot be replayed as a wallpaper.
    const std::string canonical = SpineOtaBuildCanonical(
        task.task_id, task.pack_id, "wallpaper", task.version, task.size,
        task.sha256, task.min_fw, signed_url);
    if (!SpineOtaVerifyEs256(canonical, task.signature)) {
        if (detail) *detail = "signature";
        return WallpaperOtaError::kSig;
    }
    return WallpaperOtaError::kNone;
}

bool WallpaperOta::DownloadToPartition(const WallpaperOtaTask& task,
                                       const esp_partition_t* partition,
                                       WallpaperOtaError& error) {
    error = WallpaperOtaError::kNetwork;
    if (partition == nullptr || task.size > partition->size ||
        task.size > kWallpaperOtaMaxBytes) {
        error = WallpaperOtaError::kSize;
        return false;
    }
    esp_http_client_config_t config = {};
    config.url = task.url.c_str();
    config.method = HTTP_METHOD_GET;
    config.timeout_ms = 60000;
    config.buffer_size = 4096;
    config.disable_auto_redirect = true;
    config.crt_bundle_attach = esp_crt_bundle_attach;
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) return false;
    esp_err_t result = esp_http_client_open(client, 0);
    if (result != ESP_OK) {
        esp_http_client_cleanup(client);
        return false;
    }
    const int content_length = esp_http_client_fetch_headers(client);
    const int status = esp_http_client_get_status_code(client);
    if (status != 200 || content_length <= 0 ||
        static_cast<uint32_t>(content_length) != task.size) {
        error = (status == 200) ? WallpaperOtaError::kSize : WallpaperOtaError::kNetwork;
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return false;
    }

    const size_t sector = esp_partition_get_main_flash_sector_size();
    size_t total = 0;
    size_t erased_sectors = 0;
    mbedtls_sha256_context sha;
    mbedtls_sha256_init(&sha);
    mbedtls_sha256_starts(&sha, 0);
    char buffer[1024];
    while (total < task.size) {
        const int wanted = static_cast<int>(std::min(sizeof(buffer),
            static_cast<size_t>(task.size - total)));
        const int read = esp_http_client_read(client, buffer, wanted);
        if (read <= 0) {
            error = WallpaperOtaError::kNetwork;
            mbedtls_sha256_free(&sha);
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            return false;
        }
        const size_t end = total + static_cast<size_t>(read);
        const size_t need_sectors = (end + sector - 1) / sector;
        while (erased_sectors < need_sectors) {
            const size_t offset = erased_sectors * sector;
            if (offset + sector > partition->size ||
                esp_partition_erase_range(partition, offset, sector) != ESP_OK) {
                error = WallpaperOtaError::kFlash;
                mbedtls_sha256_free(&sha);
                esp_http_client_close(client);
                esp_http_client_cleanup(client);
                return false;
            }
            ++erased_sectors;
        }
        if (esp_partition_write(partition, total, buffer, read) != ESP_OK) {
            error = WallpaperOtaError::kFlash;
            mbedtls_sha256_free(&sha);
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            return false;
        }
        mbedtls_sha256_update(&sha, reinterpret_cast<const unsigned char*>(buffer), read);
        total = end;
        Report(WallpaperOtaPhase::kDownloading, static_cast<int>(total * 100 / task.size),
               WallpaperOtaError::kNone, task.task_id, task.pack_id);
    }
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    uint8_t digest[32];
    mbedtls_sha256_finish(&sha, digest);
    mbedtls_sha256_free(&sha);
    if (!SpineOtaSha256HexEq(digest, task.sha256)) {
        error = WallpaperOtaError::kSha;
        return false;
    }
    error = WallpaperOtaError::kNone;
    return true;
}

bool WallpaperOta::Commit(const WallpaperOtaTask& task, std::string* detail) {
    nvs_handle_t handle = 0;
    esp_err_t result = nvs_open("wallpaper", NVS_READWRITE, &handle);
    if (result != ESP_OK) {
        if (detail) *detail = std::string("nvs_open:") + esp_err_to_name(result);
        return false;
    }
    auto fail = [&](const char* where, esp_err_t error) {
        nvs_close(handle);
        if (detail) *detail = std::string(where) + ":" + esp_err_to_name(error);
        return false;
    };
    if ((result = nvs_set_str(handle, "active_pack_id", task.pack_id.c_str())) != ESP_OK) {
        return fail("set_pack", result);
    }
    if ((result = nvs_set_str(handle, "active_version", task.version.c_str())) != ESP_OK) {
        return fail("set_version", result);
    }
    if ((result = nvs_set_str(handle, "last_task_id", task.task_id.c_str())) != ESP_OK) {
        return fail("set_task", result);
    }
    if ((result = nvs_set_str(handle, "last_sha256", task.sha256.c_str())) != ESP_OK) {
        return fail("set_sha", result);
    }
    if ((result = nvs_set_u8(handle, "use_factory", 0)) != ESP_OK) {
        return fail("set_use_factory", result);
    }
    result = nvs_commit(handle);
    nvs_close(handle);
    if (result != ESP_OK) {
        if (detail) *detail = std::string("nvs_commit:") + esp_err_to_name(result);
        return false;
    }
    if (detail) detail->clear();
    return true;
}

bool WallpaperOta::RunTask(const WallpaperOtaTask& task) {
    auto fail = [&](WallpaperOtaError error) {
        Report(WallpaperOtaPhase::kFailed, 0, error, task.task_id, task.pack_id);
        return false;
    };
    Report(WallpaperOtaPhase::kWaiting, 0, WallpaperOtaError::kNone,
           task.task_id, task.pack_id);
    const DeviceState state = Application::GetInstance().GetDeviceState();
    if (state == kDeviceStateActivating || state == kDeviceStateStarting ||
        state == kDeviceStateWifiConfiguring) return fail(WallpaperOtaError::kBusy);
    std::string detail;
    const WallpaperOtaError precheck = Precheck(task, &detail);
    if (precheck != WallpaperOtaError::kNone) {
        ESP_LOGE(TAG, "precheck failed %s (%s)", WallpaperOtaErrorToString(precheck),
                 detail.c_str());
        return fail(precheck);
    }
    Board::GetInstance().SetPowerSaveMode(false);
    constexpr const char* kWallpaperLabel = "wallpaper";
    const esp_partition_t* partition = esp_partition_find_first(
        ESP_PARTITION_TYPE_ANY, ESP_PARTITION_SUBTYPE_ANY, kWallpaperLabel);
    if (partition == nullptr) return fail(WallpaperOtaError::kFlash);
    Report(WallpaperOtaPhase::kDownloading, 0, WallpaperOtaError::kNone,
           task.task_id, task.pack_id);
    WallpaperOtaError download_error = WallpaperOtaError::kNetwork;
    if (!DownloadToPartition(task, partition, download_error)) return fail(download_error);

    Report(WallpaperOtaPhase::kVerifying, 100, WallpaperOtaError::kNone,
           task.task_id, task.pack_id);
    WallpaperMeta meta;
    if (!WallpaperAssets::ValidatePartition(kWallpaperLabel, &meta, &detail) ||
        meta.pack_id != task.pack_id || meta.version != task.version) {
        ESP_LOGE(TAG, "wallpaper package validation failed: %s", detail.c_str());
        return fail(WallpaperOtaError::kBundle);
    }
    MmapAssetBundle probe;
    uint8_t digest[32];
    if (!probe.Open(kWallpaperLabel, false) ||
        !probe.Sha256OfPrefix(task.size, digest) ||
        !SpineOtaSha256HexEq(digest, task.sha256)) {
        probe.Close();
        return fail(WallpaperOtaError::kSha);
    }
    probe.Close();
    Report(WallpaperOtaPhase::kApplying, 100, WallpaperOtaError::kNone,
           task.task_id, task.pack_id);
    if (!Commit(task, &detail)) {
        ESP_LOGE(TAG, "wallpaper NVS commit failed: %s", detail.c_str());
        return fail(WallpaperOtaError::kNvs);
    }
    Report(WallpaperOtaPhase::kSuccess, 100, WallpaperOtaError::kNone,
           task.task_id, task.pack_id);
    return true;
}
