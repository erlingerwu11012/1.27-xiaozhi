#include "spine_ota.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <cstring>
#include <vector>

#include <esp_app_desc.h>
#include <esp_crt_bundle.h>
#include <esp_http_client.h>
#include <esp_log.h>
#include <esp_partition.h>
#include <esp_timer.h>
#include <mbedtls/sha256.h>

#include "application.h"
#include "board.h"
#include "spine_assets.h"
#include "spine_ota_crypto.h"
#include "spine_role_preflight.h"

#define TAG "SpineOta"

namespace {

bool IsHexLowerSha256(const std::string& s) {
    if (s.size() != 64) return false;
    for (char c : s) {
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
    }
    return true;
}

bool IsAllowedId(const std::string& id) {
    if (id.empty() || id.size() > 64) return false;
    for (unsigned char c : id) {
        if (!(std::isalnum(c) || c == '_' || c == '-')) return false;
    }
    return true;
}

bool IsIpLiteralHost(const std::string& host) {
    if (host.empty()) return true;
    bool all_digit_dot = true;
    for (char c : host) {
        if (!(std::isdigit(static_cast<unsigned char>(c)) || c == '.')) {
            all_digit_dot = false;
            break;
        }
    }
    if (all_digit_dot) return true;
    if (host.front() == '[' || host.find(':') != std::string::npos) return true;
    return false;
}

std::string ToLowerAscii(const std::string& s) {
    std::string out = s;
    for (char& c : out) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return out;
}

bool HostAllowed(const std::string& host_lower) {
#ifdef CONFIG_SPINE_OTA_ALLOWED_HOSTS
    const char* list = CONFIG_SPINE_OTA_ALLOWED_HOSTS;
#else
    const char* list = "";
#endif
    if (list == nullptr || list[0] == '\0') {
        return false;
    }
    std::string hosts(list);
    size_t start = 0;
    while (start < hosts.size()) {
        size_t comma = hosts.find(',', start);
        std::string item = hosts.substr(
            start, comma == std::string::npos ? std::string::npos : comma - start);
        while (!item.empty() && (item.front() == ' ' || item.front() == '\t')) {
            item.erase(item.begin());
        }
        while (!item.empty() && (item.back() == ' ' || item.back() == '\t')) {
            item.pop_back();
        }
        if (ToLowerAscii(item) == host_lower) {
            return true;
        }
        if (comma == std::string::npos) break;
        start = comma + 1;
    }
    return false;
}

std::vector<int> ParseVersionParts(const std::string& version) {
    std::vector<int> parts;
    size_t start = 0;
    while (start < version.size()) {
        size_t dot = version.find('.', start);
        std::string seg =
            version.substr(start, dot == std::string::npos ? std::string::npos : dot - start);
        if (seg.empty()) break;
        parts.push_back(std::atoi(seg.c_str()));
        if (dot == std::string::npos) break;
        start = dot + 1;
    }
    return parts;
}

bool FirmwareMeetsMin(const std::string& current, const std::string& min_fw) {
    auto cur = ParseVersionParts(current);
    auto minv = ParseVersionParts(min_fw);
    const size_t n = std::max(cur.size(), minv.size());
    cur.resize(n, 0);
    minv.resize(n, 0);
    for (size_t i = 0; i < n; i++) {
        if (cur[i] > minv[i]) return true;
        if (cur[i] < minv[i]) return false;
    }
    return true;
}

}  // namespace

bool SpineOtaParseHttpsUrl(const std::string& url,
                           std::string& host_lower,
                           std::string& path_no_query,
                           std::string& signed_origin_path) {
    host_lower.clear();
    path_no_query.clear();
    signed_origin_path.clear();

    const std::string prefix = "https://";
    if (url.size() < prefix.size() || url.compare(0, prefix.size(), prefix) != 0) {
        return false;
    }
    if (url.find('#') != std::string::npos) {
        return false;
    }

    const size_t host_start = prefix.size();
    const size_t path_pos = url.find('/', host_start);
    const size_t query_pos = url.find('?', host_start);
    size_t host_end = url.size();
    if (path_pos != std::string::npos) host_end = path_pos;
    if (query_pos != std::string::npos && query_pos < host_end) host_end = query_pos;

    std::string host = url.substr(host_start, host_end - host_start);
    if (host.empty() || host.find('@') != std::string::npos) {
        return false;
    }
    // Reject ANY explicit port, including :443.
    if (host.find(':') != std::string::npos) {
        return false;
    }
    if (IsIpLiteralHost(host)) {
        return false;
    }
    host_lower = ToLowerAscii(host);

    if (path_pos == std::string::npos) {
        path_no_query = "/";
    } else if (query_pos != std::string::npos && query_pos > path_pos) {
        path_no_query = url.substr(path_pos, query_pos - path_pos);
    } else {
        path_no_query = url.substr(path_pos);
        // Strip query if path_pos missing but query somehow after (already handled)
        auto q = path_no_query.find('?');
        if (q != std::string::npos) {
            path_no_query = path_no_query.substr(0, q);
        }
    }
    if (path_no_query.empty()) {
        path_no_query = "/";
    }

    signed_origin_path = prefix + host_lower + path_no_query;
    return true;
}

bool SpineOtaRoleIdAllowed(const std::string& role_id, const char* allow_list) {
    if (!IsAllowedId(role_id)) {
        return false;
    }
    if (allow_list == nullptr || allow_list[0] == '\0') {
        // Empty = fail-closed.
        return false;
    }
    std::string list(allow_list);
    size_t start = 0;
    while (start <= list.size()) {
        size_t comma = list.find(',', start);
        std::string item =
            list.substr(start, comma == std::string::npos ? std::string::npos : comma - start);
        while (!item.empty() && (item.front() == ' ' || item.front() == '\t')) {
            item.erase(item.begin());
        }
        while (!item.empty() && (item.back() == ' ' || item.back() == '\t')) {
            item.pop_back();
        }
        if (item == "*" || item == role_id) {
            return true;
        }
        if (comma == std::string::npos) break;
        start = comma + 1;
    }
    return false;
}

const char* SpineOtaErrorToString(SpineOtaError err) {
    switch (err) {
        case SpineOtaError::kNone: return nullptr;
        case SpineOtaError::kBusy: return "E_BUSY";
        case SpineOtaError::kUrlDenied: return "E_URL_DENIED";
        case SpineOtaError::kRoleUnknown: return "E_ROLE_UNKNOWN";
        case SpineOtaError::kSize: return "E_SIZE";
        case SpineOtaError::kSha: return "E_SHA";
        case SpineOtaError::kSig: return "E_SIG";
        case SpineOtaError::kMinFw: return "E_MIN_FW";
        case SpineOtaError::kFlash: return "E_FLASH";
        case SpineOtaError::kNetwork: return "E_NETWORK";
        case SpineOtaError::kBundle: return "E_BUNDLE";
        case SpineOtaError::kRuntimeMismatch: return "E_SPINE_RUNTIME";
        case SpineOtaError::kUnsupported: return "E_SPINE_UNSUPPORTED";
        case SpineOtaError::kNvs: return "E_NVS";
        case SpineOtaError::kTaskMismatch: return "E_TASK_MISMATCH";
    }
    return "E_UNKNOWN";
}

const char* SpineOtaPhaseToString(SpineOtaPhase phase) {
    switch (phase) {
        case SpineOtaPhase::kIdle: return "idle";
        case SpineOtaPhase::kWaiting: return "waiting";
        case SpineOtaPhase::kDownloading: return "downloading";
        case SpineOtaPhase::kVerifying: return "verifying";
        case SpineOtaPhase::kApplying: return "applying";
        case SpineOtaPhase::kSuccess: return "success";
        case SpineOtaPhase::kFailed: return "failed";
    }
    return "idle";
}

bool SpineOta::TryAcquire(SpineOtaStatusCallback cb) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (running_) {
        return false;
    }
    running_ = true;
    last_reported_progress_ = -1;
    last_report_us_ = 0;
    status_cb_ = std::move(cb);
    return true;
}

void SpineOta::Release() {
    std::lock_guard<std::mutex> lock(mutex_);
    running_ = false;
    status_cb_ = nullptr;
    last_reported_progress_ = -1;
}

bool SpineOta::IsRunning() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return running_;
}

void SpineOta::Report(SpineOtaPhase phase, int progress, SpineOtaError error,
                      const std::string& task_id, const std::string& pack_id) {
    SpineOtaStatusCallback cb;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        cb = status_cb_;
        if (phase == SpineOtaPhase::kDownloading) {
            const int64_t now = esp_timer_get_time();
            if (progress != 100 && last_reported_progress_ >= 0 &&
                progress < last_reported_progress_ + 1 &&
                (now - last_report_us_) < 500000) {
                return;
            }
            last_reported_progress_ = progress;
            last_report_us_ = now;
        } else {
            last_reported_progress_ = -1;
        }
    }
    // Callbacks run WITHOUT holding mutex_.
    if (cb) {
        cb(phase, progress, error, task_id, pack_id);
    }
}

bool SpineOta::ParseTask(const cJSON* root, SpineOtaTask& out, SpineOtaError& err) {
    err = SpineOtaError::kBundle;
    out = {};
    if (!cJSON_IsObject(root)) {
        return false;
    }

    auto req_str = [&](const char* key, std::string& dst, size_t max_len) -> bool {
        cJSON* item = cJSON_GetObjectItem(root, key);
        if (!cJSON_IsString(item) || item->valuestring == nullptr) return false;
        dst = item->valuestring;
        if (dst.empty() || dst.size() > max_len) return false;
        return true;
    };

    if (!req_str("task_id", out.task_id, 80) ||
        !req_str("pack_id", out.pack_id, 64) ||
        !req_str("role_id", out.role_id, 64) ||
        !req_str("version", out.version, 32) ||
        !req_str("sha256", out.sha256, 64) ||
        !req_str("signature", out.signature, 512) ||
        !req_str("url", out.url, 1024) ||
        !req_str("min_fw", out.min_fw, 32)) {
        err = SpineOtaError::kBundle;
        return false;
    }

    cJSON* size_item = cJSON_GetObjectItem(root, "size");
    if (!cJSON_IsNumber(size_item) || size_item->valuedouble <= 0 ||
        size_item->valuedouble > static_cast<double>(kSpineOtaMaxBytes)) {
        err = SpineOtaError::kSize;
        return false;
    }
    out.size = static_cast<uint32_t>(size_item->valuedouble);

    if (!IsAllowedId(out.pack_id) || !IsAllowedId(out.role_id)) {
        err = SpineOtaError::kRoleUnknown;
        return false;
    }
    if (!IsHexLowerSha256(out.sha256)) {
        err = SpineOtaError::kSha;
        return false;
    }
    err = SpineOtaError::kNone;
    return true;
}

SpineOtaError SpineOta::Precheck(const SpineOtaTask& task, std::string* detail) {
    if (task.size == 0 || task.size > kSpineOtaMaxBytes) {
        if (detail) *detail = "size";
        return SpineOtaError::kSize;
    }

    std::string host, path, signed_url;
    if (!SpineOtaParseHttpsUrl(task.url, host, path, signed_url)) {
        if (detail) *detail = "url";
        return SpineOtaError::kUrlDenied;
    }
    if (!HostAllowed(host)) {
        if (detail) *detail = "host";
        return SpineOtaError::kUrlDenied;
    }

#ifdef CONFIG_SPINE_OTA_ALLOWED_ROLE_IDS
    const char* allowed = CONFIG_SPINE_OTA_ALLOWED_ROLE_IDS;
#else
    const char* allowed = "";
#endif
    if (!SpineOtaRoleIdAllowed(task.role_id, allowed)) {
        if (detail) *detail = "role";
        return SpineOtaError::kRoleUnknown;
    }

    auto* desc = esp_app_get_description();
    if (desc == nullptr || !FirmwareMeetsMin(desc->version, task.min_fw)) {
        if (detail) *detail = "min_fw";
        return SpineOtaError::kMinFw;
    }

    const std::string canonical = SpineOtaBuildCanonical(
        task.task_id, task.pack_id, task.role_id, task.version, task.size,
        task.sha256, task.min_fw, signed_url);
    if (task.signature.empty() || !SpineOtaVerifyEs256(canonical, task.signature)) {
        if (detail) *detail = "signature";
        return SpineOtaError::kSig;
    }
    return SpineOtaError::kNone;
}

bool SpineOta::DownloadToPartition(const SpineOtaTask& task,
                                   const esp_partition_t* part,
                                   SpineOtaError& err) {
    err = SpineOtaError::kNetwork;
    if (part == nullptr || task.size > part->size || task.size > kSpineOtaMaxBytes) {
        err = SpineOtaError::kSize;
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
    if (!client) {
        return false;
    }

    esp_err_t e = esp_http_client_open(client, 0);
    if (e != ESP_OK) {
        esp_http_client_cleanup(client);
        return false;
    }
    const int content_length = esp_http_client_fetch_headers(client);
    const int status = esp_http_client_get_status_code(client);
    if (status != 200) {
        ESP_LOGE(TAG, "HTTP status %d", status);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return false;
    }
    if (content_length <= 0 || static_cast<uint32_t>(content_length) != task.size) {
        ESP_LOGE(TAG, "Content-Length mismatch %d vs %u", content_length, task.size);
        err = SpineOtaError::kSize;
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return false;
    }

    const size_t sector = esp_partition_get_main_flash_sector_size();
    size_t total_written = 0;
    size_t current_sector = 0;
    mbedtls_sha256_context sha_ctx;
    mbedtls_sha256_init(&sha_ctx);
    mbedtls_sha256_starts(&sha_ctx, 0);

    char buffer[1024];
    while (total_written < task.size) {
        const int to_read = static_cast<int>(
            std::min(sizeof(buffer), static_cast<size_t>(task.size - total_written)));
        const int ret = esp_http_client_read(client, buffer, to_read);
        if (ret < 0) {
            err = SpineOtaError::kNetwork;
            mbedtls_sha256_free(&sha_ctx);
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            return false;
        }
        if (ret == 0) {
            break;
        }

        const size_t write_end = total_written + static_cast<size_t>(ret);
        if (write_end > task.size || write_end > part->size) {
            err = SpineOtaError::kFlash;
            mbedtls_sha256_free(&sha_ctx);
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            return false;
        }

        size_t needed_sectors = (write_end + sector - 1) / sector;
        while (current_sector < needed_sectors) {
            const size_t sector_start = current_sector * sector;
            if (sector_start + sector > part->size) {
                err = SpineOtaError::kFlash;
                mbedtls_sha256_free(&sha_ctx);
                esp_http_client_close(client);
                esp_http_client_cleanup(client);
                return false;
            }
            e = esp_partition_erase_range(part, sector_start, sector);
            if (e != ESP_OK) {
                err = SpineOtaError::kFlash;
                mbedtls_sha256_free(&sha_ctx);
                esp_http_client_close(client);
                esp_http_client_cleanup(client);
                return false;
            }
            current_sector++;
        }

        e = esp_partition_write(part, total_written, buffer, ret);
        if (e != ESP_OK) {
            err = SpineOtaError::kFlash;
            mbedtls_sha256_free(&sha_ctx);
            esp_http_client_close(client);
            esp_http_client_cleanup(client);
            return false;
        }
        mbedtls_sha256_update(&sha_ctx, reinterpret_cast<const unsigned char*>(buffer), ret);
        total_written += static_cast<size_t>(ret);

        const int progress = static_cast<int>(total_written * 100 / task.size);
        Report(SpineOtaPhase::kDownloading, progress, SpineOtaError::kNone, task.task_id,
               task.pack_id);
    }

    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    if (total_written != task.size) {
        err = SpineOtaError::kNetwork;
        mbedtls_sha256_free(&sha_ctx);
        return false;
    }

    uint8_t digest[32];
    mbedtls_sha256_finish(&sha_ctx, digest);
    mbedtls_sha256_free(&sha_ctx);
    if (!SpineOtaSha256HexEq(digest, task.sha256)) {
        err = SpineOtaError::kSha;
        return false;
    }
    err = SpineOtaError::kNone;
    return true;
}

bool SpineOta::RunTask(const SpineOtaTask& task) {
    // Caller must already hold the acquire lock and owns Release() after reboot/cleanup.
    // Never call Report while holding mutex_; never Release() here.
    auto finish_fail = [&](SpineOtaError e) {
        Report(SpineOtaPhase::kFailed, 0, e, task.task_id, task.pack_id);
        return false;
    };

    Report(SpineOtaPhase::kWaiting, 0, SpineOtaError::kNone, task.task_id, task.pack_id);

    auto& app = Application::GetInstance();
    const DeviceState state = app.GetDeviceState();
    // Upgrading may already have been set by Application after acquire; still reject
    // activating / wifi-config / starting races.
    if (state == kDeviceStateActivating || state == kDeviceStateStarting ||
        state == kDeviceStateWifiConfiguring) {
        return finish_fail(SpineOtaError::kBusy);
    }

    std::string detail;
    SpineOtaError pre = Precheck(task, &detail);
    if (pre != SpineOtaError::kNone) {
        ESP_LOGE(TAG, "precheck failed %s (%s)", SpineOtaErrorToString(pre), detail.c_str());
        return finish_fail(pre);
    }

    // Power-save off only; audio lifecycle is owned by Application.
    Board::GetInstance().SetPowerSaveMode(false);

    constexpr const char* kDynamicSpineLabel = "spine";
    ESP_LOGI(TAG, "writing single dynamic role partition %s", kDynamicSpineLabel);

    const esp_partition_t* part = esp_partition_find_first(
        ESP_PARTITION_TYPE_ANY, ESP_PARTITION_SUBTYPE_ANY, kDynamicSpineLabel);
    if (part == nullptr) {
        return finish_fail(SpineOtaError::kFlash);
    }

    Report(SpineOtaPhase::kDownloading, 0, SpineOtaError::kNone, task.task_id, task.pack_id);
    SpineOtaError derr = SpineOtaError::kNetwork;
    if (!DownloadToPartition(task, part, derr)) {
        ESP_LOGE(TAG, "download failed %s", SpineOtaErrorToString(derr));
        return finish_fail(derr);
    }

    Report(SpineOtaPhase::kVerifying, 100, SpineOtaError::kNone, task.task_id, task.pack_id);
    MmapAssetBundle probe;
    if (!probe.Open(kDynamicSpineLabel, true)) {
        return finish_fail(SpineOtaError::kBundle);
    }
    void* role_ptr = nullptr;
    size_t role_size = 0;
    if (!probe.GetAssetData("role.json", role_ptr, role_size)) {
        probe.Close();
        return finish_fail(SpineOtaError::kBundle);
    }
    SpineRoleMeta meta;
    std::string role_err;
    if (!SpineAssets::ParseAndValidateRoleJson(static_cast<const char*>(role_ptr), role_size,
                                               probe, meta, &role_err)) {
        ESP_LOGE(TAG, "role.json after download: %s", role_err.c_str());
        probe.Close();
        return finish_fail(SpineOtaError::kBundle);
    }
    if (meta.role_id != task.role_id || meta.version != task.version) {
        ESP_LOGE(TAG, "role/version mismatch meta=(%s,%s) task=(%s,%s)",
                 meta.role_id.c_str(), meta.version.c_str(),
                 task.role_id.c_str(), task.version.c_str());
        probe.Close();
        return finish_fail(SpineOtaError::kBundle);
    }

    // Same 4.2 compatibility gate as the startup path, before any slot switch.
    void* skel_ptr = nullptr;
    size_t skel_size = 0;
    void* atlas_ptr = nullptr;
    size_t atlas_size = 0;
    if (!probe.GetAssetData(meta.skel, skel_ptr, skel_size) ||
        !probe.GetAssetData(meta.atlas, atlas_ptr, atlas_size) ||
        skel_ptr == nullptr || atlas_ptr == nullptr) {
        ESP_LOGE(TAG, "skel/atlas unreadable after download");
        probe.Close();
        return finish_fail(SpineOtaError::kBundle);
    }
    spine_role_preflight::Result preflight = spine_role_preflight::Check(
        skel_ptr, skel_size, atlas_ptr, atlas_size, meta.skin.c_str());
    if (!preflight.ok()) {
        SpineOtaError perr = SpineOtaError::kBundle;
        if (preflight.code == spine_role_preflight::ErrorCode::kRuntimeMismatch) {
            perr = SpineOtaError::kRuntimeMismatch;
        } else if (preflight.code == spine_role_preflight::ErrorCode::kUnsupportedFeature) {
            perr = SpineOtaError::kUnsupported;
        }
        ESP_LOGE(TAG, "spine preflight failed after download: %s (%s) runtime=%s",
                 spine_role_preflight::ErrorToString(preflight.code),
                 preflight.detail.c_str(), preflight.runtime_version.c_str());
        probe.Close();
        return finish_fail(perr);
    }

    uint8_t digest[32];
    if (!probe.Sha256OfPrefix(task.size, digest) || !SpineOtaSha256HexEq(digest, task.sha256)) {
        probe.Close();
        return finish_fail(SpineOtaError::kSha);
    }
    probe.Close();

    Report(SpineOtaPhase::kApplying, 100, SpineOtaError::kNone, task.task_id, task.pack_id);
    std::string nvs_err;
    if (!SpineAssets::CommitActiveSpineSlot(SpineSlot::kA, meta.role_id, meta.version, task.task_id,
                                            task.sha256, &nvs_err)) {
        ESP_LOGE(TAG, "NVS commit failed: %s", nvs_err.c_str());
        return finish_fail(SpineOtaError::kNvs);
    }

    Report(SpineOtaPhase::kSuccess, 100, SpineOtaError::kNone, task.task_id, task.pack_id);
    // Keep running=true through Application success UI wait + Reboot.
    return true;
}
