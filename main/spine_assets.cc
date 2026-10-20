#include "spine_assets.h"

#include <cctype>
#include <functional>

#include <cJSON.h>
#include <esp_log.h>
#include <nvs.h>
#include <nvs_flash.h>

#include "assets.h"
#include "spine_role_preflight.h"

#define TAG "SpineAssets"

namespace {

bool IsAllowedRoleId(const std::string& id) {
    if (id.empty() || id.size() > 31) return false;
    for (unsigned char c : id) {
        if (!(std::isalnum(c) || c == '_' || c == '-')) return false;
    }
    return true;
}

bool IsSafeFileName(const std::string& name) {
    if (name.empty() || name.size() > 31) return false;
    return name.find('/') == std::string::npos &&
           name.find('\\') == std::string::npos &&
           name.find("..") == std::string::npos;
}

bool ParseRoleJson(const char* json, size_t len,
                   const std::function<bool(const std::string&)>& has_asset,
                   SpineRoleMeta& out, std::string* error) {
    auto fail = [&](const char* msg) {
        if (error) *error = msg;
        return false;
    };
    if (json == nullptr || len == 0) return fail("empty role.json");

    cJSON* root = cJSON_ParseWithLength(json, len);
    if (root == nullptr) return fail("role.json parse error");
    auto cleanup_fail = [&](const char* msg) {
        cJSON_Delete(root);
        return fail(msg);
    };
    auto get_str = [&](const char* key, std::string& dst) {
        cJSON* item = cJSON_GetObjectItem(root, key);
        if (!cJSON_IsString(item) || item->valuestring == nullptr) return false;
        dst = item->valuestring;
        return true;
    };

    cJSON* format = cJSON_GetObjectItem(root, "format");
    if (!cJSON_IsNumber(format) || format->valueint != 2) {
        return cleanup_fail("unsupported role.json format (require format 2)");
    }
    out = {};
    out.format = 2;
    if (!get_str("spine_runtime_version", out.spine_runtime_version) ||
        out.spine_runtime_version != "4.2") {
        return cleanup_fail("invalid spine_runtime_version (require \"4.2\")");
    }
    if (!get_str("role_id", out.role_id) || !IsAllowedRoleId(out.role_id)) {
        return cleanup_fail("invalid role_id");
    }
    if (!get_str("version", out.version) || out.version.empty() || out.version.size() > 31) {
        return cleanup_fail("invalid version");
    }
    if (!get_str("skel", out.skel) || !IsSafeFileName(out.skel)) {
        return cleanup_fail("invalid skel");
    }
    if (!get_str("atlas", out.atlas) || !IsSafeFileName(out.atlas)) {
        return cleanup_fail("invalid atlas");
    }
    if (!get_str("png", out.png) || !IsSafeFileName(out.png)) {
        return cleanup_fail("invalid png");
    }
    if (!get_str("skin", out.skin) || out.skin.empty() || out.skin.size() > 31) {
        return cleanup_fail("invalid skin");
    }
    cJSON* scale = cJSON_GetObjectItem(root, "scale");
    if (!cJSON_IsNumber(scale) || scale->valuedouble <= 0.0 || scale->valuedouble > 10.0) {
        return cleanup_fail("invalid scale");
    }
    out.scale = static_cast<float>(scale->valuedouble);
    cJSON_Delete(root);

    if (!has_asset(out.skel) || !has_asset(out.atlas) || !has_asset(out.png)) {
        return fail("skel/atlas/png missing from source");
    }
    return true;
}

}  // namespace

const char* SpineAssets::SlotLabel(SpineSlot) {
    return "spine";
}

SpineSlot SpineAssets::OtherSlot(SpineSlot slot) {
    return slot == SpineSlot::kA ? SpineSlot::kB : SpineSlot::kA;
}

SpineSlot SpineAssets::ReadActiveSlotFromNvs() {
    return SpineSlot::kA;
}

bool SpineAssets::CommitActiveSpineSlot(SpineSlot,
                                        const std::string& role_id,
                                        const std::string& version,
                                        const std::string& task_id,
                                        const std::string& sha256,
                                        std::string* error_detail) {
    auto fail = [&](const char* where, esp_err_t err) {
        if (error_detail) *error_detail = std::string(where) + ":" + esp_err_to_name(err);
        ESP_LOGE(TAG, "Commit dynamic role %s failed: %s", where, esp_err_to_name(err));
        return false;
    };
    nvs_handle_t handle = 0;
    esp_err_t err = nvs_open("spine", NVS_READWRITE, &handle);
    if (err != ESP_OK) return fail("nvs_open", err);
    auto close_fail = [&](const char* where, esp_err_t code) {
        nvs_close(handle);
        return fail(where, code);
    };
    if ((err = nvs_set_str(handle, "active_role_id", role_id.c_str())) != ESP_OK) {
        return close_fail("set_role_id", err);
    }
    if ((err = nvs_set_str(handle, "active_version", version.c_str())) != ESP_OK) {
        return close_fail("set_version", err);
    }
    if (!task_id.empty()) {
        if ((err = nvs_set_str(handle, "last_task_id", task_id.c_str())) != ESP_OK) {
            return close_fail("set_task_id", err);
        }
        if ((err = nvs_set_str(handle, "last_sha256", sha256.c_str())) != ESP_OK) {
            return close_fail("set_sha256", err);
        }
    }
    if ((err = nvs_set_str(handle, "active_source", "spine")) != ESP_OK) {
        return close_fail("set_source", err);
    }
    err = nvs_commit(handle);
    nvs_close(handle);
    if (err != ESP_OK) return fail("nvs_commit", err);
    if (error_detail) error_detail->clear();
    return true;
}

bool SpineAssets::ParseAndValidateRoleJson(const char* json, size_t len,
                                           const MmapAssetBundle& bundle,
                                           SpineRoleMeta& out,
                                           std::string* error) {
    return ParseRoleJson(json, len,
                         [&bundle](const std::string& name) { return bundle.HasAsset(name); },
                         out, error);
}

bool SpineAssets::ParseAndValidateRoleJson(const char* json, size_t len,
                                           const Assets& assets,
                                           SpineRoleMeta& out,
                                           std::string* error) {
    return ParseRoleJson(json, len,
                         [&assets](const std::string& name) { return assets.HasAsset(name); },
                         out, error);
}

bool SpineAssets::ValidateRoleData(bool dynamic_bundle, const char* source_label) {
    void* role_ptr = nullptr;
    size_t role_size = 0;
    const bool role_ok = dynamic_bundle
        ? dynamic_bundle_.GetAssetData("role.json", role_ptr, role_size)
        : Assets::GetInstance().GetAssetData("role.json", role_ptr, role_size);
    if (!role_ok || role_ptr == nullptr || role_size == 0) {
        ESP_LOGE(TAG, "role.json unreadable from %s", source_label);
        return false;
    }

    std::string err;
    const bool meta_ok = dynamic_bundle
        ? ParseAndValidateRoleJson(static_cast<const char*>(role_ptr), role_size,
                                   dynamic_bundle_, meta_, &err)
        : ParseAndValidateRoleJson(static_cast<const char*>(role_ptr), role_size,
                                   Assets::GetInstance(), meta_, &err);
    if (!meta_ok) {
        ESP_LOGE(TAG, "role.json invalid from %s: %s", source_label, err.c_str());
        meta_ = {};
        return false;
    }

    void* skel_ptr = nullptr;
    size_t skel_size = 0;
    void* atlas_ptr = nullptr;
    size_t atlas_size = 0;
    const bool files_ok = dynamic_bundle
        ? dynamic_bundle_.GetAssetData(meta_.skel, skel_ptr, skel_size) &&
              dynamic_bundle_.GetAssetData(meta_.atlas, atlas_ptr, atlas_size)
        : Assets::GetInstance().GetAssetData(meta_.skel, skel_ptr, skel_size) &&
              Assets::GetInstance().GetAssetData(meta_.atlas, atlas_ptr, atlas_size);
    if (!files_ok || skel_ptr == nullptr || atlas_ptr == nullptr) {
        ESP_LOGE(TAG, "skel/atlas unreadable from %s", source_label);
        meta_ = {};
        return false;
    }
    const auto preflight = spine_role_preflight::Check(
        skel_ptr, skel_size, atlas_ptr, atlas_size, meta_.skin.c_str());
    if (!preflight.ok()) {
        ESP_LOGE(TAG, "spine preflight failed from %s: %s (%s) runtime=%s",
                 source_label, spine_role_preflight::ErrorToString(preflight.code),
                 preflight.detail.c_str(), preflight.runtime_version.c_str());
        meta_ = {};
        return false;
    }
    return true;
}

bool SpineAssets::TryOpenDynamic() {
    dynamic_bundle_.Close();
    meta_ = {};
    if (!dynamic_bundle_.Open("spine", true)) return false;
    if (!ValidateRoleData(true, "spine")) {
        dynamic_bundle_.Close();
        return false;
    }
    uses_dynamic_partition_ = true;
    ready_ = true;
    ESP_LOGI(TAG, "online Spine role ready id=%s version=%s",
             meta_.role_id.c_str(), meta_.version.c_str());
    return true;
}

bool SpineAssets::TryOpenFactoryAssets() {
    meta_ = {};
    if (!Assets::GetInstance().partition_valid() ||
        !Assets::GetInstance().checksum_valid()) {
        ESP_LOGE(TAG, "factory assets partition is unavailable");
        return false;
    }
    if (!ValidateRoleData(false, "assets")) return false;
    uses_dynamic_partition_ = false;
    ready_ = true;
    ESP_LOGI(TAG, "factory Spine role ready id=%s version=%s",
             meta_.role_id.c_str(), meta_.version.c_str());
    return true;
}

bool SpineAssets::Initialize() {
    if (ready_) return true;
    Shutdown();
    ESP_LOGI(TAG, "[SPINEBOOT] prefer online spine partition, then factory assets");
    if (TryOpenDynamic()) return true;
    ESP_LOGW(TAG, "online spine partition unavailable; falling back to factory assets");
    if (TryOpenFactoryAssets()) return true;
    ESP_LOGE(TAG, "[SPINEBOOT] no valid Spine role in spine or assets");
    return false;
}

void SpineAssets::Shutdown() {
    dynamic_bundle_.Close();
    meta_ = {};
    ready_ = false;
    uses_dynamic_partition_ = false;
}

const char* SpineAssets::active_label() const {
    return uses_dynamic_partition_ ? "spine" : "assets";
}

bool SpineAssets::GetAssetData(const std::string& name, void*& ptr, size_t& size) {
    if (!ready_) return false;
    return uses_dynamic_partition_
        ? dynamic_bundle_.GetAssetData(name, ptr, size)
        : Assets::GetInstance().GetAssetData(name, ptr, size);
}
