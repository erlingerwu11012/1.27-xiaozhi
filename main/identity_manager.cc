#include "identity_manager.h"
#include "settings.h"

#include <esp_log.h>
#include <cJSON.h>

#include <algorithm>

static const char* TAG = "IdentityManager";

IdentityManager::IdentityManager() {
    Load();
}

bool IdentityManager::AddUser(const UserIdentity& user) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (user.user_id.empty()) return false;
    if ((int)users_.size() >= kMaxUsers) return false;
    for (auto& u : users_) {
        if (u.user_id == user.user_id) return false;
    }
    UserIdentity normalized = user;
    if (!normalized.face_id.empty() && normalized.face_ids.empty()) {
        normalized.face_ids.push_back(normalized.face_id);
    }
    if (!normalized.voice_id.empty() && normalized.voice_ids.empty()) {
        normalized.voice_ids.push_back(normalized.voice_id);
    }
    users_.push_back(std::move(normalized));
    Save();
    ESP_LOGI(TAG, "AddUser: %s (%s)", user.user_id.c_str(), user.display_name.c_str());
    return true;
}

bool IdentityManager::RemoveUser(const std::string& user_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto it = users_.begin(); it != users_.end(); ++it) {
        if (it->user_id == user_id) {
            ESP_LOGI(TAG, "RemoveUser: %s", user_id.c_str());
            users_.erase(it);
            Save();
            return true;
        }
    }
    return false;
}

bool IdentityManager::UpdateUser(const UserIdentity& user) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& u : users_) {
        if (u.user_id == user.user_id) {
            u.display_name = user.display_name;
            u.face_id = user.face_id;
            u.voice_id = user.voice_id;
            u.face_ids = user.face_ids;
            u.voice_ids = user.voice_ids;
            if (!u.face_id.empty() && u.face_ids.empty()) {
                u.face_ids.push_back(u.face_id);
            }
            if (!u.voice_id.empty() && u.voice_ids.empty()) {
                u.voice_ids.push_back(u.voice_id);
            }
            u.enabled = user.enabled;
            Save();
            ESP_LOGI(TAG, "UpdateUser: %s", user.user_id.c_str());
            return true;
        }
    }
    return false;
}

bool IdentityManager::FindByUserId(const std::string& user_id,
                                   UserIdentity* out) const {
    if (!out) return false;
    std::lock_guard<std::mutex> lock(mutex_);
    for (const auto& u : users_) {
        if (u.user_id == user_id) {
            *out = u;
            return true;
        }
    }
    return false;
}

bool IdentityManager::FindByFaceId(const std::string& face_id,
                                   UserIdentity* out) const {
    if (!out) return false;
    std::lock_guard<std::mutex> lock(mutex_);
    if (face_id.empty()) return false;
    for (const auto& u : users_) {
        if (u.enabled &&
            (u.face_id == face_id ||
             std::find(u.face_ids.begin(), u.face_ids.end(), face_id) !=
                 u.face_ids.end())) {
            *out = u;
            return true;
        }
    }
    return false;
}

bool IdentityManager::FindByVoiceId(const std::string& voice_id,
                                   UserIdentity* out) const {
    if (!out) return false;
    std::lock_guard<std::mutex> lock(mutex_);
    if (voice_id.empty()) return false;
    for (const auto& u : users_) {
        if (u.enabled &&
            (u.voice_id == voice_id ||
             std::find(u.voice_ids.begin(), u.voice_ids.end(), voice_id) !=
                 u.voice_ids.end())) {
            *out = u;
            return true;
        }
    }
    return false;
}

void IdentityManager::ApplyFaceIdentityBindings(
    std::vector<FaceIdentityBinding> bindings) {
    std::lock_guard<std::mutex> lock(mutex_);

    std::vector<FaceIdentityBinding> normalized;
    normalized.reserve(std::min(bindings.size(),
                                static_cast<size_t>(kMaxFaceIdentityBindings)));
    for (auto& binding : bindings) {
        if (binding.face_profile_id.empty() || binding.user_id.empty() ||
            binding.display_name.empty() || binding.face_profile_id.size() > 64 ||
            binding.user_id.size() > 64 || binding.display_name.size() > 96) {
            continue;
        }
        const auto existing = std::find_if(
            normalized.begin(), normalized.end(), [&binding](const auto& item) {
                return item.face_profile_id == binding.face_profile_id;
            });
        // A profile may belong to only one user.  Reject duplicate entries
        // instead of letting server list order decide a user's identity.
        if (existing != normalized.end()) {
            continue;
        }
        normalized.emplace_back(std::move(binding));
        if (normalized.size() >= kMaxFaceIdentityBindings) break;
    }

    face_identity_bindings_ = std::move(normalized);
    ESP_LOGI(TAG, "Face identity bindings refreshed: %u",
             static_cast<unsigned>(face_identity_bindings_.size()));
}

bool IdentityManager::ResolveFaceIdentity(
    const std::string& face_profile_id, FaceIdentityBinding* out) const {
    if (!out || face_profile_id.empty()) return false;
    std::lock_guard<std::mutex> lock(mutex_);
    const auto it = std::find_if(
        face_identity_bindings_.begin(), face_identity_bindings_.end(),
        [&face_profile_id](const auto& item) {
            return item.face_profile_id == face_profile_id;
        });
    if (it == face_identity_bindings_.end()) return false;
    *out = *it;
    return true;
}

std::vector<UserIdentity> IdentityManager::GetAll() {
    std::lock_guard<std::mutex> lock(mutex_);
    return users_;
}

bool IdentityManager::Save() {
    cJSON* root = cJSON_CreateArray();
    for (auto& u : users_) {
        cJSON* item = cJSON_CreateObject();
        cJSON_AddStringToObject(item, "uid", u.user_id.c_str());
        cJSON_AddStringToObject(item, "name", u.display_name.c_str());
        cJSON_AddStringToObject(item, "fid", u.face_id.c_str());
        cJSON_AddStringToObject(item, "vid", u.voice_id.c_str());
        cJSON* face_ids = cJSON_AddArrayToObject(item, "face_ids");
        for (const auto& id : u.face_ids) {
            cJSON_AddItemToArray(face_ids, cJSON_CreateString(id.c_str()));
        }
        cJSON* voice_ids = cJSON_AddArrayToObject(item, "voice_ids");
        for (const auto& id : u.voice_ids) {
            cJSON_AddItemToArray(voice_ids, cJSON_CreateString(id.c_str()));
        }
        cJSON_AddBoolToObject(item, "en", u.enabled);
        cJSON_AddItemToArray(root, item);
    }
    char* str = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!str) return false;
    Settings s("identity", true);
    bool okay = s.SetString("users", str) == ESP_OK;
    free(str);
    if (s.Commit() != ESP_OK || !okay) return false;
    ESP_LOGI(TAG, "Save: %zu users", users_.size());
    return true;
}

void IdentityManager::Load() {
    Settings s("identity", false);
    std::string json = s.GetString("users", "");
    if (json.empty()) return;
    cJSON* root = cJSON_Parse(json.c_str());
    if (!root || !cJSON_IsArray(root)) {
        if (root) cJSON_Delete(root);
        return;
    }
    int n = cJSON_GetArraySize(root);
    for (int i = 0; i < n && i < kMaxUsers; i++) {
        cJSON* item = cJSON_GetArrayItem(root, i);
        if (!item) continue;
        UserIdentity u;
        cJSON* v;
        v = cJSON_GetObjectItem(item, "uid");
        if (v && v->valuestring) u.user_id = v->valuestring;
        v = cJSON_GetObjectItem(item, "name");
        if (v && v->valuestring) u.display_name = v->valuestring;
        v = cJSON_GetObjectItem(item, "fid");
        if (v && v->valuestring) u.face_id = v->valuestring;
        v = cJSON_GetObjectItem(item, "vid");
        if (v && v->valuestring) u.voice_id = v->valuestring;
        cJSON* face_ids = cJSON_GetObjectItem(item, "face_ids");
        if (cJSON_IsArray(face_ids)) {
            cJSON* id = nullptr;
            cJSON_ArrayForEach(id, face_ids) {
                if (cJSON_IsString(id) && id->valuestring) {
                    u.face_ids.emplace_back(id->valuestring);
                }
            }
        }
        cJSON* voice_ids = cJSON_GetObjectItem(item, "voice_ids");
        if (cJSON_IsArray(voice_ids)) {
            cJSON* id = nullptr;
            cJSON_ArrayForEach(id, voice_ids) {
                if (cJSON_IsString(id) && id->valuestring) {
                    u.voice_ids.emplace_back(id->valuestring);
                }
            }
        }
        if (!u.face_id.empty() && u.face_ids.empty()) u.face_ids.push_back(u.face_id);
        if (!u.voice_id.empty() && u.voice_ids.empty()) u.voice_ids.push_back(u.voice_id);
        v = cJSON_GetObjectItem(item, "en");
        u.enabled = v ? cJSON_IsTrue(v) : true;
        if (!u.user_id.empty()) {
            users_.push_back(u);
        }
    }
    cJSON_Delete(root);
    ESP_LOGI(TAG, "Load: %zu users", users_.size());
}

bool IdentityManager::ReplaceFromServer(const std::vector<UserIdentity>& users) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (users.size() > kMaxUsers) return false;
    auto before = users_; users_ = users;
    if (!Save()) { users_ = before; return false; }
    face_identity_bindings_.erase(std::remove_if(face_identity_bindings_.begin(), face_identity_bindings_.end(), [&](const auto& binding) {
        return std::none_of(users_.begin(), users_.end(), [&](const auto& user) { return user.user_id == binding.user_id; });
    }), face_identity_bindings_.end());
    return true;
}
