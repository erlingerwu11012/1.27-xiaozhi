#include "wallpaper_assets.h"

#include <cctype>

#include <cJSON.h>
#include <esp_err.h>
#include <esp_log.h>

#include "settings.h"

#define TAG "WallpaperAssets"

namespace {

bool IsSafeId(const std::string& value, size_t max_len) {
    if (value.empty() || value.size() > max_len) return false;
    for (unsigned char c : value) {
        if (!(std::isalnum(c) || c == '_' || c == '-')) return false;
    }
    return true;
}

bool IsSafeFileName(const std::string& name) {
    return !name.empty() && name.size() <= 31 &&
           name.find('/') == std::string::npos &&
           name.find('\\') == std::string::npos &&
           name.find("..") == std::string::npos;
}

}  // namespace

bool WallpaperAssets::ParseAndValidateManifest(const char* json, size_t len,
                                               const MmapAssetBundle& bundle,
                                               WallpaperMeta& out,
                                               std::string* error) {
    auto fail = [&](const char* message) {
        if (error) *error = message;
        return false;
    };
    if (json == nullptr || len == 0) return fail("empty wallpaper.json");
    cJSON* root = cJSON_ParseWithLength(json, len);
    if (root == nullptr) return fail("wallpaper.json parse error");
    auto cleanup_fail = [&](const char* message) {
        cJSON_Delete(root);
        return fail(message);
    };
    auto get_str = [&](const char* key, std::string& dst) {
        cJSON* item = cJSON_GetObjectItem(root, key);
        if (!cJSON_IsString(item) || item->valuestring == nullptr) return false;
        dst = item->valuestring;
        return true;
    };

    cJSON* format = cJSON_GetObjectItem(root, "format");
    if (!cJSON_IsNumber(format) || format->valueint != 1) {
        return cleanup_fail("unsupported wallpaper.json format (require format 1)");
    }
    out = {};
    out.format = 1;
    if (!get_str("pack_id", out.pack_id) || !IsSafeId(out.pack_id, 64)) {
        return cleanup_fail("invalid pack_id");
    }
    if (!get_str("version", out.version) || out.version.size() > 31) {
        return cleanup_fail("invalid version");
    }
    if (!get_str("default_id", out.default_id) || !IsSafeId(out.default_id, 31)) {
        return cleanup_fail("invalid default_id");
    }
    cJSON* items = cJSON_GetObjectItem(root, "items");
    if (!cJSON_IsArray(items) || cJSON_GetArraySize(items) < 1 ||
        cJSON_GetArraySize(items) > 16) {
        return cleanup_fail("invalid items");
    }
    const int count = cJSON_GetArraySize(items);
    for (int i = 0; i < count; ++i) {
        cJSON* item = cJSON_GetArrayItem(items, i);
        cJSON* id = cJSON_GetObjectItem(item, "id");
        cJSON* file = cJSON_GetObjectItem(item, "file");
        if (!cJSON_IsString(id) || id->valuestring == nullptr ||
            !cJSON_IsString(file) || file->valuestring == nullptr) {
            return cleanup_fail("invalid item");
        }
        const std::string id_value = id->valuestring;
        const std::string file_value = file->valuestring;
        if (!IsSafeId(id_value, 31) || !IsSafeFileName(file_value) ||
            !bundle.HasAsset(file_value) ||
            !out.files_by_id.emplace(id_value, file_value).second) {
            return cleanup_fail("invalid or duplicate wallpaper item");
        }
    }
    cJSON_Delete(root);
    if (out.files_by_id.find(out.default_id) == out.files_by_id.end()) {
        return fail("default_id is not in items");
    }
    return true;
}

bool WallpaperAssets::ValidatePartition(const char* label, WallpaperMeta* out,
                                        std::string* error) {
    MmapAssetBundle probe;
    if (!probe.Open(label, false)) {
        if (error) *error = "bundle invalid";
        return false;
    }
    void* manifest = nullptr;
    size_t manifest_size = 0;
    WallpaperMeta parsed;
    const bool ok = probe.GetAssetData("wallpaper.json", manifest, manifest_size) &&
                    ParseAndValidateManifest(static_cast<const char*>(manifest), manifest_size,
                                             probe, parsed, error);
    probe.Close();
    if (ok && out) *out = std::move(parsed);
    return ok;
}

bool WallpaperAssets::Initialize() {
    if (ready_) return true;
    Shutdown();
    if (!bundle_.Open("wallpaper", false)) {
        ESP_LOGI(TAG, "No valid online wallpaper package; use factory room.png");
        return false;
    }
    void* manifest = nullptr;
    size_t manifest_size = 0;
    std::string error;
    if (!bundle_.GetAssetData("wallpaper.json", manifest, manifest_size) ||
        !ParseAndValidateManifest(static_cast<const char*>(manifest), manifest_size,
                                  bundle_, meta_, &error)) {
        ESP_LOGW(TAG, "online wallpaper rejected: %s", error.c_str());
        Shutdown();
        return false;
    }
    ready_ = true;
    ESP_LOGI(TAG, "online wallpaper ready pack=%s version=%s items=%u",
             meta_.pack_id.c_str(), meta_.version.c_str(),
             static_cast<unsigned>(meta_.files_by_id.size()));
    return true;
}

void WallpaperAssets::Shutdown() {
    bundle_.Close();
    meta_ = {};
    ready_ = false;
}

std::string WallpaperAssets::ResolveSelectedId() const {
    if (!ready_) return {};
    Settings settings("wallpaper", false);
    if (settings.GetBool("use_factory", false)) return {};
    const std::string selected = settings.GetString("selected_id");
    if (meta_.files_by_id.find(selected) != meta_.files_by_id.end()) return selected;
    return meta_.default_id;
}

std::string WallpaperAssets::SelectedId() const {
    return ResolveSelectedId();
}

bool WallpaperAssets::GetSelectedAssetData(void*& ptr, size_t& size,
                                           std::string* selected_id) {
    if (!ready_) return false;
    const std::string id = ResolveSelectedId();
    auto item = meta_.files_by_id.find(id);
    if (item == meta_.files_by_id.end()) return false;
    if (!bundle_.GetAssetData(item->second, ptr, size)) return false;
    if (selected_id) *selected_id = id;
    return ptr != nullptr && size != 0;
}

bool WallpaperAssets::Select(const std::string& wallpaper_id) {
    if (!ready_ || meta_.files_by_id.find(wallpaper_id) == meta_.files_by_id.end()) {
        return false;
    }
    Settings settings("wallpaper", true);
    if (settings.SetString("selected_id", wallpaper_id) != ESP_OK) {
        ESP_LOGW(TAG, "failed to persist selected wallpaper id=%s", wallpaper_id.c_str());
        return false;
    }
    settings.SetBool("use_factory", false);
    ESP_LOGI(TAG, "selected online wallpaper id=%s", wallpaper_id.c_str());
    return true;
}

bool WallpaperAssets::UseFactoryWallpaper() {
    Settings settings("wallpaper", true);
    if (settings.SetBool("use_factory", true) != ESP_OK) return false;
    ESP_LOGI(TAG, "selected factory room.png wallpaper");
    return true;
}
