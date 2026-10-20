#include "habit_manager.h"
#include "settings.h"
#include <esp_log.h>
#include <cJSON.h>
#include <cstring>
#include <cstdio>
#include <algorithm>
#include "person_turn.h"
#include "weekly_schedule.h"
#include <mbedtls/sha256.h>
#include <memory>

#define TAG "HabitManager"

namespace {
bool IsUsrId(const std::string& id) {
    return IsPersonId(id);
}

void MigrateHabitIdentity(Habit& h) {
    if (h.creator_person_id.empty() && IsUsrId(h.owner_user_id)) {
        h.creator_person_id = h.owner_user_id;
    }
    if (!h.creator_person_id.empty()) {
        h.owner_user_id = h.creator_person_id;
    }
    if (h.recipient_person_id.empty()) {
        if (IsUsrId(h.owner_user_id)) {
            h.recipient_person_id = h.owner_user_id;
            h.delivery_unbound = false;
        } else {
            h.delivery_unbound = true;
        }
    } else if (!IsUsrId(h.recipient_person_id) && !(h.recipient_person_id == "all" && !h.sync_account.empty())) {
        h.recipient_person_id.clear();
        h.delivery_unbound = true;
    }
}
}  // namespace

HabitManager::HabitManager() {
    Load();
}

int HabitManager::Add(int hour, int minute, int advance_minutes,
                       const std::string& intent, const std::string& description,
                       const std::string& source) {
    return Add(hour, minute, advance_minutes, intent, description, source, "default");
}

int HabitManager::Add(int hour, int minute, int advance_minutes,
                       const std::string& intent, const std::string& description,
                       const std::string& source, const std::string& owner,
                       const std::string& recipient_person_id,
                       const std::string& recipient_display_name, int repeat_days) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (repeat_days < 1 || repeat_days > 127 || hour < 0 || hour > 23 || minute < 0 || minute > 59) return -1;

    // 检查相同 intent 是否已存在，避免重复
    for (auto& h : habits_) {
        if (h.owner_user_id == owner && h.intent == intent && h.hour == hour && h.minute == minute && h.repeat_days == repeat_days) {
            ESP_LOGI(TAG, "Habit already exists id=%d intent=%s", h.id, intent.c_str());
            // Automatic rediscovery does not undo a user's pause or replace a
            // manually authored rule. Explicit confirm remains available.
            return h.id;
        }
    }
    if ((int)habits_.size() >= kMaxHabits) return -1;

    Habit a;
    a.id                = next_id_++;
    a.hour              = hour;
    a.minute            = minute;
    a.advance_minutes   = std::clamp(advance_minutes, 0, 30);
    a.intent            = Utf8Prefix(intent, 64);
    a.description       = Utf8Prefix(description, 96);
    a.repeat_days       = repeat_days;
    a.confidence        = 1;
    a.consecutive_reject = 0;
    a.total_fires       = 0;
    a.enabled           = true;
    a.source            = (source == "manual") ? "manual" : "auto";
    a.owner_user_id     = owner.empty() ? "default" : owner;
    a.creator_person_id = IsUsrId(a.owner_user_id) ? a.owner_user_id : "";
    a.recipient_person_id = recipient_person_id;
    a.recipient_display_name_snapshot = recipient_display_name;
    MigrateHabitIdentity(a);
    habits_.push_back(a);
    if (!Save()) { habits_.pop_back(); --next_id_; return -1; }
    ESP_LOGI(TAG,
             "Added habit id=%d %02d:%02d creator=%s recipient=%s unbound=%d",
             a.id, hour, minute, a.owner_user_id.c_str(),
             a.recipient_person_id.empty() ? "-" : a.recipient_person_id.c_str(),
             a.delivery_unbound ? 1 : 0);
    return a.id;
}

bool HabitManager::Delete(int id) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto it = habits_.begin(); it != habits_.end(); ++it) {
        if (it->id == id) {
            const auto before = habits_;
            habits_.erase(it);
            if (!Save()) { habits_ = before; return false; }
            ESP_LOGI(TAG, "Deleted habit id=%d", id);
            return true;
        }
    }
    return false;
}

void HabitManager::DeleteById(int id) {
    // 内部无锁版本，调用方已持有 mutex_
    for (auto it = habits_.begin(); it != habits_.end(); ++it) {
        if (it->id == id) {
            habits_.erase(it);
            ESP_LOGI(TAG, "Auto-deleted habit id=%d (confidence<=0)", id);
            return;
        }
    }
}

bool HabitManager::Confirm(int id) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& h : habits_) {
        if (h.id == id) {
            const auto before = h;
            h.confidence++;
            h.consecutive_reject = 0;
            h.total_fires++;
            h.enabled = true; // 重新启用（如果之前被禁用）
            if (!Save()) { h = before; return false; }
            ESP_LOGI(TAG, "Habit id=%d confirmed, confidence=%d", id, h.confidence);
            return true;
        }
    }
    return false;
}

HabitManager::RejectResult HabitManager::Reject(int id) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& h : habits_) {
        if (h.id == id) {
            const auto before = h;
            h.confidence = std::max(0, h.confidence - 1);
            h.consecutive_reject++;
            ESP_LOGI(TAG, "Habit id=%d rejected, confidence=%d, consec_reject=%d",
                     id, h.confidence, h.consecutive_reject);
            // 手动设定的习惯永不因跳过自动暂停或删除；只有明确
            // Delete 命令可以永久移除它。自动学习的习惯则以连续
            // 三次“今天不需要”作为暂停阈值，绝不自动删除。
            if (h.source != "manual") {
                if (h.consecutive_reject >= 3) {
                    // 连续拒绝3次，自动禁用
                    h.enabled = false;
                    ESP_LOGI(TAG, "Habit id=%d auto-disabled (consec_reject>=3)", id);
                    if (!Save()) { h = before; return RejectResult::kStorageError; }
                    return RejectResult::kAutoDisabled;
                }
            }
            if (!Save()) { h = before; return RejectResult::kStorageError; }
            return RejectResult::kRejected;
        }
    }
    return RejectResult::kNotFound;
}

std::vector<Habit> HabitManager::GetAll() {
    std::lock_guard<std::mutex> lock(mutex_);
    return habits_;
}

std::vector<Habit> HabitManager::GetAll(const std::string& owner) {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<Habit> result;
    for (auto& h : habits_) {
        const std::string& creator =
            h.creator_person_id.empty() ? h.owner_user_id : h.creator_person_id;
        if (h.owner_user_id == owner ||
            creator == owner) {
            result.push_back(h);
        }
    }
    return result;
}

std::vector<std::string> HabitManager::GetListLines() {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<std::string> lines;
    int idx = 1;
    for (const auto& h : habits_) {
        char buf[128];
        snprintf(buf, sizeof(buf), "[%d] %02d:%02d  %s  (置信度:%d 触发:%d次%s)",
                 idx++, h.hour, h.minute,
                 h.description.c_str(),
                 h.confidence,
                 h.total_fires,
                 h.enabled ? "" : " 已禁用");
        lines.push_back(buf);
    }
    return lines;
}

void HabitManager::CheckAndFire(int hour, int minute, int day_key,
                                  std::function<bool(const Habit&)> on_fire, time_t now) {
    // 计算提前触发的时间
    // 对每个习惯，触发时间 = habit.hour:habit.minute - advance_minutes
    std::lock_guard<std::mutex> lock(mutex_);
    if (!now) now = time(nullptr);

    for (auto& h : habits_) {
        if (!h.enabled) continue;
        const auto due = HabitOccurrenceAt(now, h.hour, h.minute, h.advance_minutes, h.repeat_days);
        if (due && due != h.last_occurrence) {
            Habit occurrence = h; occurrence.occurrence_at = due;
            if (!on_fire(occurrence)) continue;
            h.last_occurrence = due;
            h.total_fires++;
            Save();
            ESP_LOGI(TAG, "Habit fired: id=%d %s", h.id, h.description.c_str());
        }
    }
}

void HabitManager::Load() {
    Settings s("habits", false);
    std::string json = s.GetJson("list", "");
    next_id_ = s.GetInt("next_id", 1);
    habits_.clear();
    if (json.empty()) return;

    cJSON* root = cJSON_Parse(json.c_str());
    if (!root) return;

    int n = cJSON_GetArraySize(root);
    for (int i = 0; i < n && i < kMaxHabits; i++) {
        cJSON* item = cJSON_GetArrayItem(root, i);
        if (!item) continue;
        Habit h;
        auto gi = [&](const char* k, int def) -> int {
            cJSON* v = cJSON_GetObjectItem(item, k);
            return v ? v->valueint : def;
        };
        auto gs = [&](const char* k) -> std::string {
            cJSON* v = cJSON_GetObjectItem(item, k);
            return (v && v->valuestring) ? v->valuestring : "";
        };
        h.id                = gi("id", 0);
        h.hour              = gi("h",  0);
        h.minute            = gi("m",  0);
        h.advance_minutes   = gi("adv", 2);
        h.confidence        = gi("conf", 1);
        h.consecutive_reject = gi("cr", 0);
        h.total_fires       = gi("tf", 0);
        h.enabled           = (bool)gi("en", 1);
        h.repeat_days       = gi("repeat_days", 127);
        h.last_occurrence   = static_cast<time_t>(strtoll(gs("last_occurrence").c_str(), nullptr, 10));
        h.intent            = gs("intent");
        h.description       = gs("desc");
        h.source            = gs("src");
        if (h.source.empty()) h.source = "auto";
        // 兼容旧字段 "o"，优先读 "uid"
        h.owner_user_id     = gs("uid");
        if (h.owner_user_id.empty()) h.owner_user_id = gs("o");
        if (h.owner_user_id.empty()) h.owner_user_id = "default";
        h.creator_person_id = gs("cid");
        h.recipient_person_id = gs("rid");
        h.recipient_display_name_snapshot = gs("rdn");
        h.delivery_unbound = gi("unb", 0) != 0;
        h.sync_id = gs("sync_id"); h.sync_account = gs("sync_account"); h.content_hash = gs("content_hash");
        MigrateHabitIdentity(h);
        if (h.id >= next_id_) next_id_ = h.id + 1;
        habits_.push_back(h);
    }
    cJSON_Delete(root);
    ESP_LOGI(TAG, "Loaded %d habits", (int)habits_.size());
}

bool HabitManager::Save(int* storage_error) {
    if (storage_error) *storage_error = ESP_FAIL;
    cJSON* root = cJSON_CreateArray();
    for (const auto& h : habits_) {
        cJSON* item = cJSON_CreateObject();
        cJSON_AddNumberToObject(item, "id",     h.id);
        cJSON_AddNumberToObject(item, "h",      h.hour);
        cJSON_AddNumberToObject(item, "m",      h.minute);
        cJSON_AddNumberToObject(item, "adv",    h.advance_minutes);
        cJSON_AddNumberToObject(item, "conf",   h.confidence);
        cJSON_AddNumberToObject(item, "cr",     h.consecutive_reject);
        cJSON_AddNumberToObject(item, "tf",     h.total_fires);
        cJSON_AddNumberToObject(item, "en",     h.enabled ? 1 : 0);
        cJSON_AddNumberToObject(item, "repeat_days", h.repeat_days);
        cJSON_AddStringToObject(item, "timezone", h.timezone.c_str());
        cJSON_AddStringToObject(item, "last_occurrence", std::to_string(h.last_occurrence).c_str());
        cJSON_AddStringToObject(item, "intent", h.intent.c_str());
        cJSON_AddStringToObject(item, "desc",   h.description.c_str());
        cJSON_AddStringToObject(item, "src",    h.source.c_str());
        cJSON_AddStringToObject(item, "uid",   h.owner_user_id.c_str());
        cJSON_AddStringToObject(item, "cid", h.creator_person_id.c_str());
        cJSON_AddStringToObject(item, "rid", h.recipient_person_id.c_str());
        cJSON_AddStringToObject(
            item, "rdn", h.recipient_display_name_snapshot.c_str());
        cJSON_AddNumberToObject(item, "unb", h.delivery_unbound ? 1 : 0);
        cJSON_AddStringToObject(item, "sync_id", h.sync_id.c_str());
        cJSON_AddStringToObject(item, "sync_account", h.sync_account.c_str());
        cJSON_AddStringToObject(item, "content_hash", h.content_hash.c_str());
        cJSON_AddItemToArray(root, item);
    }
    char* str = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!str) return false;

    Settings s("habits", true);
    esp_err_t error = s.SetJson("list", str);
    if (error == ESP_OK) error = s.SetInt("next_id", next_id_);
    if (error != ESP_OK) {
        nvs_stats_t stats{}; const auto status = nvs_get_stats(nullptr, &stats);
        ESP_LOGW(TAG, "Habit save failed err=0x%x bytes=%u stats_ok=%d free=%u total=%u",
                 static_cast<int>(error), static_cast<unsigned>(strlen(str)), status == ESP_OK,
                 static_cast<unsigned>(stats.free_entries), static_cast<unsigned>(stats.total_entries));
    }
    free(str);
    const auto commit_error = s.Commit();
    if (error == ESP_OK) error = commit_error;
    if (storage_error) *storage_error = error;
    return error == ESP_OK;
}

std::string HabitManager::Sync(const cJSON* p) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto text = [p](const char* key) -> std::string {
        auto v = cJSON_GetObjectItem(p, key); return cJSON_IsString(v) && v->valuestring ? v->valuestring : "";
    };
    auto integer = [p](const char* key, int low, int high) -> int {
        auto v = cJSON_GetObjectItem(p, key);
        return cJSON_IsNumber(v) && v->valuedouble == v->valueint && v->valueint >= low && v->valueint <= high ? v->valueint : -1;
    };
    const auto account = text("account_id"), key = text("sync_id"), hash = text("content_hash"), recipient = text("recipient_person_id");
    const auto desc = text("description"), intent = text("intent"), name = text("recipient_display_name");
    const int hour = integer("hour",0,23), minute = integer("minute",0,59), advance = integer("advance_minutes",0,30), days = integer("repeat_days",1,127);
    auto enabled_item = cJSON_GetObjectItem(p,"enabled"); const bool enabled = cJSON_IsTrue(enabled_item);
    auto fail = [&](const char* error) { return std::string("{\"ok\":false,\"persisted\":false,\"error\":\"") + error + "\"}"; };
    if (account.empty() || key.empty() || key.size()>20 || key.find_first_not_of("0123456789") != std::string::npos || key[0]=='0' || hash.size()!=64 ||
        (recipient!="all" && !IsPersonId(recipient)) || desc.empty() || desc.size()>96 || intent.empty() || intent.size()>64 || name.size()>96 ||
        hour<0 || minute<0 || advance<0 || days<0 || !cJSON_IsBool(enabled_item)) return fail("invalid_config");
    std::string canonical;
    for (const auto& value : {account,key,recipient,name,intent,desc,std::to_string(hour),std::to_string(minute),std::to_string(advance),std::to_string(days),std::string(enabled?"1":"0")})
        canonical += std::to_string(value.size()) + ":" + value;
    unsigned char digest[32]; mbedtls_sha256(reinterpret_cast<const unsigned char*>(canonical.data()),canonical.size(),digest,0);
    char hex[65]; for(int i=0;i<32;++i) snprintf(hex+i*2,3,"%02x",digest[i]);
    if (hash != hex) return fail("hash_mismatch");
    const auto before = habits_; const int old_next = next_id_;
    auto found = habits_.end();
    for(auto it=habits_.begin();it!=habits_.end();++it) if(it->sync_account==account && it->sync_id==key) { found=it; break; }
    if (found != habits_.end() && found->content_hash == hash && found->enabled == enabled) {
        return "{\"ok\":true,\"persisted\":true,\"sync_id\":\""+key+"\",\"content_hash\":\""+hash+"\",\"device_rule_id\":"+std::to_string(found->id)+",\"enabled\":"+(enabled?"true":"false")+"}";
    }
    if(found==habits_.end()) {
        // Adopt a legacy record only if identity and every authored field match uniquely.
        int count=0;
        for(auto it=habits_.begin();it!=habits_.end();++it) if(it->sync_id.empty() && it->source=="manual" &&
            it->recipient_person_id==recipient && !it->delivery_unbound &&
            (recipient=="all" ? it->creator_person_id.empty() && it->owner_user_id=="default" : it->creator_person_id==recipient && it->owner_user_id==recipient) &&
            it->intent==intent && it->description==desc && it->hour==hour && it->minute==minute && it->advance_minutes==advance && it->repeat_days==days && it->enabled==enabled) {found=it; ++count;}
        if(count>1) return fail("legacy_ambiguous");
    }
    if(found==habits_.end()) {
        if(!enabled) { // Desired absence is verified; do not allocate a deleted never-synced rule.
            return "{\"ok\":true,\"persisted\":true,\"sync_id\":\""+key+"\",\"content_hash\":\""+hash+"\",\"device_rule_id\":0,\"enabled\":false}";
        }
        if(habits_.size()>=kMaxHabits) return fail("quota_exceeded");
        Habit h{}; h.id=next_id_++; h.confidence=1; h.source="manual";
        habits_.push_back(h); found=std::prev(habits_.end());
    }
    auto& h=*found; h.sync_account=account; h.sync_id=key; h.content_hash=hash;
    h.hour=hour;h.minute=minute;h.advance_minutes=advance;h.repeat_days=days;h.intent=intent;h.description=desc;h.enabled=enabled;
    h.owner_user_id=recipient=="all"?"default":recipient;h.creator_person_id=recipient=="all"?"":recipient;
    h.recipient_person_id=recipient;h.recipient_display_name_snapshot=name;h.delivery_unbound=false;h.source="manual";
    const int rule_id=h.id; int error=ESP_OK;
    if (!Save(&error)) {habits_=before;next_id_=old_next;
        return fail(error==ESP_ERR_NVS_NOT_ENOUGH_SPACE || error==ESP_ERR_NVS_NO_FREE_PAGES ? "storage_full":"storage_error");}
    return "{\"ok\":true,\"persisted\":true,\"sync_id\":\""+key+"\",\"content_hash\":\""+hash+"\",\"device_rule_id\":"+std::to_string(rule_id)+",\"enabled\":"+(enabled?"true":"false")+"}";
}

bool HabitManager::RetirePerson(const std::string& person, bool legacy) {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto before = habits_;
    habits_.erase(std::remove_if(habits_.begin(), habits_.end(), [&](const auto& value) {
        return value.owner_user_id == person || value.creator_person_id == person ||
            value.recipient_person_id == person || (legacy &&
            (value.owner_user_id.empty() || value.owner_user_id == "default"));
    }), habits_.end());
    if (!Save()) { habits_ = before; return false; }
    return true;
}
