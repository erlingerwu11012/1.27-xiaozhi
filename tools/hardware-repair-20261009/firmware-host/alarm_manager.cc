#include "person_turn.h"
#include "alarm_manager.h"
#include "settings.h"
#include <esp_log.h>
#include <cJSON.h>
#include <cstring>
#include <ctime>

#define TAG "AlarmManager"

namespace {
bool IsUsrId(const std::string& id) {
    return IsPersonId(id);
}

void MigrateAlarmIdentity(Alarm& a) {
    if (a.creator_person_id.empty() && IsUsrId(a.owner_user_id)) {
        a.creator_person_id = a.owner_user_id;
    }
    if (!a.creator_person_id.empty()) {
        a.owner_user_id = a.creator_person_id;
    }
    if (a.recipient_person_id.empty()) {
        if (IsUsrId(a.owner_user_id)) {
            a.recipient_person_id = a.owner_user_id;
            a.delivery_unbound = false;
        } else {
            a.delivery_unbound = true;
        }
    } else if (!IsUsrId(a.recipient_person_id)) {
        a.recipient_person_id.clear();
        a.delivery_unbound = true;
    }
}
}  // namespace

AlarmManager::AlarmManager() {
    Load();
}

int AlarmManager::Add(int hour, int minute, const std::string& label, uint8_t repeat_days) {
    return Add(hour, minute, label, repeat_days, "default");
}

int AlarmManager::Add(int hour, int minute, const std::string& label,
                      uint8_t repeat_days, const std::string& owner,
                      const std::string& recipient_person_id,
                      const std::string& recipient_display_name) {
    std::lock_guard<std::mutex> lock(mutex_);
    if ((int)alarms_.size() >= kMaxAlarms) return -1;
    if (hour < 0 || hour > 23 || minute < 0 || minute > 59 || repeat_days > 127) return -1;
    Alarm a;
    a.id             = next_id_++;
    a.hour           = hour;
    a.minute         = minute;
    a.label          = Utf8Prefix(label, 32);
    a.enabled        = true;
    a.repeat_days    = repeat_days;
    a.owner_user_id  = owner.empty() ? "default" : owner;
    a.creator_person_id = IsUsrId(a.owner_user_id) ? a.owner_user_id : "";
    a.recipient_person_id = recipient_person_id;
    a.recipient_display_name_snapshot = recipient_display_name;
    MigrateAlarmIdentity(a);
    alarms_.push_back(a);
    if (!Save()) { alarms_.pop_back(); --next_id_; return -1; }
    ESP_LOGI(TAG,
             "Added alarm id=%d %02d:%02d creator=%s recipient=%s unbound=%d",
             a.id, hour, minute, a.owner_user_id.c_str(),
             a.recipient_person_id.empty() ? "-" : a.recipient_person_id.c_str(),
             a.delivery_unbound ? 1 : 0);
    return a.id;
}

bool AlarmManager::Delete(int id) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto it = alarms_.begin(); it != alarms_.end(); ++it) {
        if (it->id == id) {
            const auto before = alarms_;
            alarms_.erase(it);
            if (!Save()) { alarms_ = before; return false; }
            ESP_LOGI(TAG, "Deleted alarm id=%d", id);
            return true;
        }
    }
    return false;
}

std::vector<std::string> AlarmManager::GetListLines() {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<std::string> lines;
    static const char* day_names[] = {"日","一","二","三","四","五","六"};
    for (auto& a : alarms_) {
        // 构造重复规则描述
        std::string repeat_str;
        if (a.repeat_days == 0x7F) {
            repeat_str = "每天";
        } else if (a.repeat_days == 0x3E) { // bit1~bit5 = 周一到周五
            repeat_str = "工作日";
        } else if (a.repeat_days == 0x41) { // bit0+bit6 = 周日+周六
            repeat_str = "周末";
        } else if (a.repeat_days == 0) {
            repeat_str = "仅一次";
        } else {
            repeat_str = "每周";
            for (int d = 0; d < 7; d++) {
                if (a.repeat_days & (1 << d)) {
                    repeat_str += day_names[d];
                }
            }
        }
        char buf[96];
        snprintf(buf, sizeof(buf), "[%d] %02d:%02d %s [%s]%s",
                 a.id, a.hour, a.minute,
                 a.label.c_str(),
                 repeat_str.c_str(),
                 a.enabled ? "" : " (已关闭)");
        lines.push_back(buf);
    }
    return lines;
}

std::vector<Alarm> AlarmManager::GetAll() {
    std::lock_guard<std::mutex> lock(mutex_);
    return alarms_;
}

std::vector<Alarm> AlarmManager::GetAll(const std::string& owner) {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<Alarm> result;
    for (auto& a : alarms_) {
        const std::string& creator =
            a.creator_person_id.empty() ? a.owner_user_id : a.creator_person_id;
        if (a.owner_user_id == owner ||
            creator == owner) {
            result.push_back(a);
        }
    }
    return result;
}

void AlarmManager::CheckAndFire(int hour, int minute, int wday, int day_key,
                                 std::function<void(const Alarm&)> on_fire) {
    int cur_min = hour * 60 + minute;
    std::vector<Alarm> deliveries;

    // ── 贪睡检查（优先于正常闹钟）────────────────────────────────────────────
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (snooze_target_minute_ >= 0 && cur_min == snooze_target_minute_
            && cur_min != last_fired_minute_) {
            last_fired_minute_ = cur_min;
            snooze_target_minute_ = -1;
            ESP_LOGI(TAG, "Snooze fired: %s", snoozed_alarm_.label.c_str());
            deliveries.push_back(snoozed_alarm_);
        }
    }

    {
    std::lock_guard<std::mutex> lock(mutex_);
    bool need_save = false;
    for (auto& a : alarms_) {
        if (!a.enabled || a.hour != hour || a.minute != minute) continue;
        // 检查重复规则：repeat_days 的 bit[wday] 是否为 1
        // repeat_days==0 表示仅一次（任何天都响，响完禁用）
        if (a.repeat_days != 0 && !(a.repeat_days & (1 << wday))) continue;
        auto fired = last_fired_day_by_id_.find(a.id);
        if (a.last_triggered_day == day_key || (fired != last_fired_day_by_id_.end() &&
            fired->second == day_key)) {
            continue;
        }

        const Alarm before = a;
        a.last_triggered_day = day_key;
        a.last_triggered_at = static_cast<int64_t>(time(nullptr));
        if (a.repeat_days == 0) a.enabled = false;
        // Persist the claimed occurrence before delivery; reboot cannot ring it twice.
        if (!Save()) {
            a = before;
            ESP_LOGE(TAG, "Alarm occurrence persistence failed: id=%d", a.id);
            continue;
        }
        last_fired_minute_ = cur_min;
        last_fired_day_by_id_[a.id] = day_key;
        snoozed_alarm_ = a; // 保存副本，供贪睡使用
        ESP_LOGI(TAG, "Alarm fired: id=%d %s (repeat=0x%02X, wday=%d)",
                 a.id, a.label.c_str(), a.repeat_days, wday);
        deliveries.push_back(a);

        // 仅一次的闹钟触发后自动禁用
        if (a.repeat_days == 0) {
            a.enabled = false;
            need_save = true;
        }
    }
    if (need_save) Save();
    }
    for (const auto& alarm : deliveries) on_fire(alarm);
}

void AlarmManager::Snooze(int delay_minutes) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (snoozed_alarm_.id == 0) {
        ESP_LOGW(TAG, "Snooze: no alarm to snooze");
        return;
    }
    // 计算贪睡目标时间
    int base = snoozed_alarm_.hour * 60 + snoozed_alarm_.minute;
    // 如果已经贪睡过，从当前时间算
    if (snooze_target_minute_ >= 0) base = snooze_target_minute_;
    int target = (base + delay_minutes) % (24 * 60);
    snooze_target_minute_ = target;
    // 重置 last_fired_minute_ 以允许新时间触发
    last_fired_minute_ = -1;
    ESP_LOGI(TAG, "Snooze set: %s will fire at %02d:%02d (+%d min)",
             snoozed_alarm_.label.c_str(), target / 60, target % 60, delay_minutes);
}

void AlarmManager::DismissCurrent() {
    std::lock_guard<std::mutex> lock(mutex_);
    snooze_target_minute_ = -1;
    snoozed_alarm_ = {};
    ESP_LOGI(TAG, "Alarm dismissed");
}

// ── NVS 持久化（JSON 序列化）────────────────────────────────────────────────

void AlarmManager::Load() {
    Settings s("alarms");
    std::string json = s.GetJson("list", "");
    if (json.empty()) return;

    cJSON* root = cJSON_Parse(json.c_str());
    if (!root) return;

    int n = cJSON_GetArraySize(root);
    for (int i = 0; i < n; i++) {
        cJSON* item = cJSON_GetArrayItem(root, i);
        Alarm a;
        a.id      = cJSON_GetObjectItem(item, "id")  ? cJSON_GetObjectItem(item, "id")->valueint  : 0;
        a.hour    = cJSON_GetObjectItem(item, "h")   ? cJSON_GetObjectItem(item, "h")->valueint   : 0;
        a.minute  = cJSON_GetObjectItem(item, "m")   ? cJSON_GetObjectItem(item, "m")->valueint   : 0;
        a.enabled = cJSON_GetObjectItem(item, "en")  ? (bool)cJSON_GetObjectItem(item, "en")->valueint : true;
        // repeat_days: 兼容旧数据（无此字段时默认 0x7F=每天）
        cJSON* rd = cJSON_GetObjectItem(item, "rd");
        a.repeat_days = rd ? (uint8_t)rd->valueint : 0x7F;
        cJSON* lbl = cJSON_GetObjectItem(item, "lbl");
        a.label   = (lbl && lbl->valuestring) ? lbl->valuestring : "";
        cJSON* jo = cJSON_GetObjectItem(item, "uid");
        if (!jo) jo = cJSON_GetObjectItem(item, "o");
        a.owner_user_id = (jo && jo->valuestring) ? jo->valuestring : "default";
        cJSON* jcid = cJSON_GetObjectItem(item, "cid");
        a.creator_person_id =
            (jcid && jcid->valuestring) ? jcid->valuestring : "";
        cJSON* jrid = cJSON_GetObjectItem(item, "rid");
        a.recipient_person_id =
            (jrid && jrid->valuestring) ? jrid->valuestring : "";
        cJSON* jrn = cJSON_GetObjectItem(item, "rdn");
        a.recipient_display_name_snapshot =
            (jrn && jrn->valuestring) ? jrn->valuestring : "";
        cJSON* junb = cJSON_GetObjectItem(item, "unb");
        a.delivery_unbound = junb ? junb->valueint != 0 : false;
        cJSON* last_day = cJSON_GetObjectItem(item, "fday");
        cJSON* last_time = cJSON_GetObjectItem(item, "fat");
        a.last_triggered_day = cJSON_IsNumber(last_day) ? last_day->valueint : 0;
        a.last_triggered_at = cJSON_IsNumber(last_time) ? static_cast<int64_t>(last_time->valuedouble) : 0;
        MigrateAlarmIdentity(a);
        if (a.id >= next_id_) next_id_ = a.id + 1;
        alarms_.push_back(a);
    }
    cJSON_Delete(root);
    ESP_LOGI(TAG, "Loaded %d alarms", (int)alarms_.size());
}

bool AlarmManager::Save() {
    cJSON* root = cJSON_CreateArray();
    for (auto& a : alarms_) {
        cJSON* item = cJSON_CreateObject();
        cJSON_AddNumberToObject(item, "id",  a.id);
        cJSON_AddNumberToObject(item, "h",   a.hour);
        cJSON_AddNumberToObject(item, "m",   a.minute);
        cJSON_AddNumberToObject(item, "en",  a.enabled ? 1 : 0);
        cJSON_AddNumberToObject(item, "rd",  a.repeat_days);
        cJSON_AddStringToObject(item, "lbl", a.label.c_str());
        cJSON_AddStringToObject(item, "uid", a.owner_user_id.c_str());
        cJSON_AddStringToObject(item, "cid", a.creator_person_id.c_str());
        cJSON_AddStringToObject(item, "rid", a.recipient_person_id.c_str());
        cJSON_AddStringToObject(
            item, "rdn", a.recipient_display_name_snapshot.c_str());
        cJSON_AddNumberToObject(item, "unb", a.delivery_unbound ? 1 : 0);
        cJSON_AddNumberToObject(item, "fday", a.last_triggered_day);
        cJSON_AddNumberToObject(item, "fat", static_cast<double>(a.last_triggered_at));
        cJSON_AddItemToArray(root, item);
    }
    char* str = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!str) return false;

    Settings s("alarms", true);
    bool okay = s.SetJson("list", str) == ESP_OK;
    free(str);
    return s.Commit() == ESP_OK && okay;
}

bool AlarmManager::RetirePerson(const std::string& person, bool legacy) {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto before = alarms_;
    alarms_.erase(std::remove_if(alarms_.begin(), alarms_.end(), [&](const auto& value) {
        return value.owner_user_id == person || value.creator_person_id == person ||
            value.recipient_person_id == person || (legacy &&
            (value.owner_user_id.empty() || value.owner_user_id == "default"));
    }), alarms_.end());
    if (!Save()) { alarms_ = before; return false; }
    if (snoozed_alarm_.owner_user_id == person || (legacy && snoozed_alarm_.owner_user_id == "default")) snooze_target_minute_ = -1;
    return true;
}
