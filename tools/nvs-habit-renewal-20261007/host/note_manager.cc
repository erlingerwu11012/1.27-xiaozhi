#include "note_manager.h"
#include "settings.h"
#include <esp_log.h>
#include <cJSON.h>
#include <cstring>
#include <ctime>
#include <algorithm>
#include "person_turn.h"
#include "weekly_schedule.h"

#define TAG "NoteManager"

namespace {
bool IsUsrId(const std::string& id) {
    return IsPersonId(id);
}
}  // namespace

void NoteManager::MigrateIdentityFields(Note& n) {
    if (n.creator_person_id.empty() && IsUsrId(n.owner_user_id)) {
        n.creator_person_id = n.owner_user_id;
    }
    if (!n.creator_person_id.empty()) {
        n.owner_user_id = n.creator_person_id;
    }
    if (n.recipient_person_id.empty()) {
        if (IsUsrId(n.owner_user_id)) {
            n.recipient_person_id = n.owner_user_id;
            n.delivery_unbound = false;
        } else if (n.remind_at > 0) {
            n.delivery_unbound = true;
        }
    } else if (!IsUsrId(n.recipient_person_id)) {
        n.recipient_person_id.clear();
        if (n.remind_at > 0) n.delivery_unbound = true;
    }
}

NoteManager::NoteManager() {
    Load();
}

int NoteManager::Add(const std::string& text, uint32_t remind_at) {
    return Add(text, remind_at, "default");
}

int NoteManager::Add(const std::string& text, uint32_t remind_at,
                     const std::string& owner,
                     const std::string& priority,
                     const std::string& attention_policy,
                     int pre_alert_minutes,
                     const std::string& recipient_person_id,
                     const std::string& recipient_display_name, int repeat_days,
                     std::string* error_code) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (error_code) error_code->clear();
    if ((int)notes_.size() >= kMaxNotes) {
        if (error_code) *error_code = "note_limit_reached";
        return -1;
    }
    if (repeat_days < 0 || repeat_days > 127 || (repeat_days && !remind_at)) {
        if (error_code) *error_code = "invalid_repeat_days";
        return -1;
    }
    Note n;
    n.id             = next_id_++;
    n.ts             = (uint32_t)time(nullptr);
    n.remind_at      = remind_at;
    n.fired          = false;
    n.snooze_count   = 0;
    n.text           = Utf8Prefix(text, kMaxTextBytes);
    n.repeat_days    = repeat_days;
    n.repeat_hour    = ((static_cast<int64_t>(remind_at) + kScheduleUtcOffset) % 86400) / 3600;
    n.repeat_minute  = ((static_cast<int64_t>(remind_at) + kScheduleUtcOffset) % 3600) / 60;
    if (repeat_days && !WeekdayAllowed(repeat_days, ScheduleDay(remind_at))) {
        n.remind_at = static_cast<uint32_t>(NextWeeklyDue(remind_at, n.repeat_hour, n.repeat_minute, repeat_days));
    }
    n.owner_user_id  = owner.empty() ? "default" : owner;
    n.creator_person_id = IsUsrId(n.owner_user_id) ? n.owner_user_id : "";
    n.recipient_person_id = recipient_person_id;
    n.recipient_display_name_snapshot = recipient_display_name;
    n.priority = priority == "high" ? "high" : "normal";
    n.attention_policy =
        attention_policy == "pickup" || attention_policy == "medication"
            ? attention_policy : "general";
    n.pre_alert_minutes =
        n.priority == "high" && n.attention_policy == "pickup"
            ? std::clamp(pre_alert_minutes, 0, 30) : 0;
    MigrateIdentityFields(n);
    notes_.insert(notes_.begin(), n);
    int storage_error = ESP_OK;
    if (!Save(&storage_error)) {
        notes_.erase(notes_.begin()); --next_id_;
        if (error_code) *error_code = storage_error == ESP_ERR_NVS_NOT_ENOUGH_SPACE || storage_error == ESP_ERR_NVS_NO_FREE_PAGES
            ? "storage_full" : "storage_write_failed";
        return -1;
    }
    ESP_LOGI(TAG,
             "Added note id=%d remind_at=%u creator=%s recipient=%s unbound=%d",
             n.id, n.remind_at, n.owner_user_id.c_str(),
             n.recipient_person_id.empty() ? "-" : n.recipient_person_id.c_str(),
             n.delivery_unbound ? 1 : 0);
    return n.id;
}

bool NoteManager::Delete(int id) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto it = notes_.begin(); it != notes_.end(); ++it) {
        if (it->id == id) {
            const auto before = notes_;
            notes_.erase(it);
            if (!Save()) { notes_ = before; return false; }
            ESP_LOGI(TAG, "Deleted note id=%d", id);
            return true;
        }
    }
    return false;
}

bool NoteManager::CompleteOccurrence(int id) {
    { std::lock_guard<std::mutex> lock(mutex_);
      for (const auto& n : notes_) if (n.id == id && n.repeat_days) return true; }
    return Delete(id);
}

bool NoteManager::Snooze(int id, int delay_sec) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& n : notes_) {
        if (n.id == id) {
            const auto before = n;
            if (n.snooze_count >= kMaxSnooze) {
                ESP_LOGW(TAG, "Note id=%d snooze limit reached (%d)", id, kMaxSnooze);
                return false;
            }
            n.remind_at   = (uint32_t)(time(nullptr) + delay_sec);
            n.fired       = false;
            n.snooze_count++;
            if (!Save()) { n = before; return false; }
            ESP_LOGI(TAG, "Snoozed note id=%d by %ds (count=%d)", id, delay_sec, n.snooze_count);
            return true;
        }
    }
    return false;
}

std::vector<Note> NoteManager::GetAll() {
    std::lock_guard<std::mutex> lock(mutex_);
    return notes_;
}

std::vector<Note> NoteManager::GetAll(const std::string& owner) {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<Note> result;
    for (auto& n : notes_) {
        const std::string& creator =
            n.creator_person_id.empty() ? n.owner_user_id : n.creator_person_id;
        if (n.owner_user_id == owner ||
            creator == owner) {
            result.push_back(n);
        }
    }
    return result;
}

std::vector<std::string> NoteManager::GetListLines() {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<std::string> lines;
    uint32_t now_ts = (uint32_t)time(nullptr);
    for (const auto& n : notes_) {
        std::string line = n.text;
        if (n.remind_at > 0) {
            if (n.fired) {
                // 已触发：计算过期多久
                uint32_t elapsed = now_ts > n.remind_at ? now_ts - n.remind_at : 0;
                if (elapsed < 3600) {
                    char buf[32];
                    snprintf(buf, sizeof(buf), " [已提醒，%lu分钟前]", (unsigned long)(elapsed / 60));
                    line += buf;
                } else if (elapsed < 86400) {
                    char buf[32];
                    snprintf(buf, sizeof(buf), " [已提醒，%lu小时前]", (unsigned long)(elapsed / 3600));
                    line += buf;
                } else {
                    char buf[32];
                    snprintf(buf, sizeof(buf), " [已过期 %lu天]", (unsigned long)(elapsed / 86400));
                    line += buf;
                }
            } else if (now_ts > n.remind_at) {
                // 到点但还没触发（设备不在线时错过）
                line += " [已过时间，待提醒]";
            } else {
                // 未到点：显示提醒时间
                time_t t = (time_t)n.remind_at;
                struct tm tm_info;
                localtime_r(&t, &tm_info);
                char time_buf[32];
                strftime(time_buf, sizeof(time_buf), " [提醒:%m/%d %H:%M]", &tm_info);
                line += time_buf;
            }
        } else {
            // 无提醒时间（待办）：显示创建时间
            if (n.ts > 0) {
                uint32_t age = now_ts > n.ts ? now_ts - n.ts : 0;
                if (age < 86400) {
                    line += " [待办，今天]";
                } else {
                    char buf[32];
                    snprintf(buf, sizeof(buf), " [待办，%lu天前]", (unsigned long)(age / 86400));
                    line += buf;
                }
            } else {
                line += " [待办]";
            }
        }
        lines.push_back(line);
        if ((int)lines.size() >= 8) break;
    }
    return lines;
}

void NoteManager::CheckAndRemind(uint32_t now_ts,
                                  std::function<bool(const Note&)> on_remind) {
    std::lock_guard<std::mutex> lock(mutex_);
    bool changed = false;
    for (auto& n : notes_) {
        if (n.repeat_days && n.remind_at && now_ts > n.remind_at + 86400u) {
            // Offline weeks do not create a burst of obsolete daily instances.
            n.remind_at = static_cast<uint32_t>(NextWeeklyDue(now_ts - 1, n.repeat_hour, n.repeat_minute, n.repeat_days));
            n.fired = false; changed = true;
        }
        const uint32_t trigger_at =
            n.remind_at > static_cast<uint32_t>(n.pre_alert_minutes * 60)
                ? n.remind_at -
                      static_cast<uint32_t>(n.pre_alert_minutes * 60)
                : n.remind_at;
        if (n.remind_at > 0 && !n.fired && now_ts >= trigger_at) {
            ESP_LOGI(TAG, "Note id=%d remind triggered: %s", n.id, n.text.c_str());
            if (on_remind(n)) {
                n.last_occurrence = n.remind_at;
                if (n.repeat_days) {
                    n.remind_at = static_cast<uint32_t>(NextWeeklyDue(n.remind_at, n.repeat_hour, n.repeat_minute, n.repeat_days));
                    n.fired = false; n.snooze_count = 0;
                } else n.fired = true;
                changed = true;
            }
        }
    }
    if (changed) Save();
}

void NoteManager::PruneExpired(uint32_t now_ts) {
    std::lock_guard<std::mutex> lock(mutex_);
    bool changed = false;
    auto it = notes_.begin();
    while (it != notes_.end()) {
        bool should_delete = false;
        if (!it->repeat_days && it->remind_at > 0 && it->fired) {
            // 有提醒时间且已触发：超过 24 小时删除
            if (now_ts > it->remind_at + kFiredExpirySec) {
                should_delete = true;
                ESP_LOGI(TAG, "PruneExpired: fired note id=%d expired (>24h)", it->id);
            }
        } else if (it->remind_at == 0 && it->ts > 0) {
            // 无提醒时间（待办）：超过 7 天删除
            if (now_ts > it->ts + kTodoExpirySec) {
                should_delete = true;
                ESP_LOGI(TAG, "PruneExpired: todo note id=%d expired (>7d)", it->id);
            }
        }
        if (should_delete) {
            it = notes_.erase(it);
            changed = true;
        } else {
            ++it;
        }
    }
    if (changed) Save();
}

void NoteManager::Load() {
    Settings s("notes", false);
    std::string json = s.GetJson("list", "");
    next_id_ = s.GetInt("next_id", 1);
    notes_.clear();
    if (json.empty()) return;

    cJSON* root = cJSON_Parse(json.c_str());
    if (!root) return;

    int count = cJSON_GetArraySize(root);
    for (int i = 0; i < count && i < kMaxNotes; i++) {
        cJSON* item = cJSON_GetArrayItem(root, i);
        if (!item) continue;
        Note n;
        cJSON* jid  = cJSON_GetObjectItem(item, "id");
        cJSON* jts  = cJSON_GetObjectItem(item, "ts");
        cJSON* jtxt = cJSON_GetObjectItem(item, "text");
        cJSON* jra  = cJSON_GetObjectItem(item, "ra");
        cJSON* jf   = cJSON_GetObjectItem(item, "f");
        cJSON* jsc  = cJSON_GetObjectItem(item, "sc");
        if (!jid || !jtxt) continue;
        n.id          = jid->valueint;
        n.ts          = jts  ? (uint32_t)jts->valueint  : 0;
        n.text        = jtxt->valuestring ? jtxt->valuestring : "";
        n.remind_at   = jra  ? (uint32_t)jra->valueint  : 0;
        n.fired       = jf   ? (bool)jf->valueint        : false;
        n.snooze_count = jsc ? jsc->valueint              : 0;
        auto repeat = cJSON_GetObjectItem(item, "repeat_days");
        n.repeat_days = cJSON_IsNumber(repeat) ? repeat->valueint : 0;
        auto hour = cJSON_GetObjectItem(item, "repeat_hour");
        auto minute = cJSON_GetObjectItem(item, "repeat_minute");
        n.repeat_hour = cJSON_IsNumber(hour) ? hour->valueint : 0;
        n.repeat_minute = cJSON_IsNumber(minute) ? minute->valueint : 0;
        auto last = cJSON_GetObjectItem(item, "last_occurrence");
        n.last_occurrence = cJSON_IsNumber(last) ? static_cast<uint32_t>(last->valuedouble) : 0;
        cJSON* jo = cJSON_GetObjectItem(item, "uid");
        if (!jo) jo = cJSON_GetObjectItem(item, "o");
        n.owner_user_id = (jo && jo->valuestring) ? jo->valuestring : "default";
        cJSON* jcid = cJSON_GetObjectItem(item, "cid");
        n.creator_person_id =
            (jcid && jcid->valuestring) ? jcid->valuestring : "";
        cJSON* jrid = cJSON_GetObjectItem(item, "rid");
        n.recipient_person_id =
            (jrid && jrid->valuestring) ? jrid->valuestring : "";
        cJSON* jrn = cJSON_GetObjectItem(item, "rdn");
        n.recipient_display_name_snapshot =
            (jrn && jrn->valuestring) ? jrn->valuestring : "";
        cJSON* junb = cJSON_GetObjectItem(item, "unb");
        n.delivery_unbound = junb ? junb->valueint != 0 : false;
        cJSON* jp = cJSON_GetObjectItem(item, "priority");
        n.priority = (jp && jp->valuestring &&
                      std::strcmp(jp->valuestring, "high") == 0)
            ? "high" : "normal";
        cJSON* jap = cJSON_GetObjectItem(item, "attention_policy");
        n.attention_policy = (jap && jap->valuestring)
            ? jap->valuestring : "general";
        cJSON* jpre = cJSON_GetObjectItem(item, "pre_alert_minutes");
        n.pre_alert_minutes = jpre ? jpre->valueint : 0;
        MigrateIdentityFields(n);
        notes_.push_back(n);
    }
    cJSON_Delete(root);
    ESP_LOGI(TAG, "Loaded %d notes", (int)notes_.size());
}

bool NoteManager::Save(int* storage_error) {
    if (storage_error) *storage_error = ESP_FAIL;
    cJSON* root = cJSON_CreateArray();
    for (const auto& n : notes_) {
        cJSON* item = cJSON_CreateObject();
        cJSON_AddNumberToObject(item, "id",   n.id);
        cJSON_AddNumberToObject(item, "ts",   (double)n.ts);
        cJSON_AddStringToObject(item, "text", n.text.c_str());
        cJSON_AddNumberToObject(item, "ra",   (double)n.remind_at);
        cJSON_AddNumberToObject(item, "f",    n.fired ? 1 : 0);
        cJSON_AddNumberToObject(item, "sc",   n.snooze_count);
        cJSON_AddNumberToObject(item, "repeat_days", n.repeat_days);
        cJSON_AddNumberToObject(item, "repeat_hour", n.repeat_hour);
        cJSON_AddNumberToObject(item, "repeat_minute", n.repeat_minute);
        cJSON_AddNumberToObject(item, "last_occurrence", n.last_occurrence);
        cJSON_AddStringToObject(item, "timezone", n.timezone.c_str());
        cJSON_AddStringToObject(item, "uid",  n.owner_user_id.c_str());
        cJSON_AddStringToObject(item, "cid", n.creator_person_id.c_str());
        cJSON_AddStringToObject(item, "rid", n.recipient_person_id.c_str());
        cJSON_AddStringToObject(
            item, "rdn", n.recipient_display_name_snapshot.c_str());
        cJSON_AddNumberToObject(item, "unb", n.delivery_unbound ? 1 : 0);
        cJSON_AddStringToObject(item, "priority", n.priority.c_str());
        cJSON_AddStringToObject(
            item, "attention_policy", n.attention_policy.c_str());
        cJSON_AddNumberToObject(
            item, "pre_alert_minutes", n.pre_alert_minutes);
        cJSON_AddItemToArray(root, item);
    }
    char* str = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!str) return false;

    Settings s("notes", true);
    esp_err_t error = s.SetInt("next_id", next_id_);
    if (error == ESP_OK) error = s.SetJson("list", str);
    if (error != ESP_OK) {
        nvs_stats_t stats{};
        const auto stats_error = nvs_get_stats(nullptr, &stats);
        ESP_LOGW(TAG, "Note save failed err=0x%x json_bytes=%u notes=%u nvs_stats_ok=%d used=%u free=%u total=%u",
                 static_cast<int>(error), static_cast<unsigned>(strlen(str)),
                 static_cast<unsigned>(notes_.size()), stats_error == ESP_OK,
                 static_cast<unsigned>(stats.used_entries), static_cast<unsigned>(stats.free_entries),
                 static_cast<unsigned>(stats.total_entries));
    }
    free(str);
    // Preserve the first failure; commit errors must not disguise space errors.
    const auto commit_error = s.Commit();
    if (error == ESP_OK) error = commit_error;
    if (storage_error) *storage_error = error;
    return error == ESP_OK;
}

bool NoteManager::RetirePerson(const std::string& person, bool legacy) {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto before = notes_;
    notes_.erase(std::remove_if(notes_.begin(), notes_.end(), [&](const auto& value) {
        return value.owner_user_id == person || value.creator_person_id == person ||
            value.recipient_person_id == person || (legacy &&
            (value.owner_user_id.empty() || value.owner_user_id == "default"));
    }), notes_.end());
    if (!Save()) { notes_ = before; return false; }
    return true;
}
