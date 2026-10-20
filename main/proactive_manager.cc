#include "proactive_manager.h"
#include "alarm_manager.h"
#include "habit_manager.h"
#include "note_manager.h"
#include "settings.h"

#include <esp_log.h>
#include <cstdio>
#include <cJSON.h>

static const char* TAG = "ProactiveManager";

ProactiveManager::ProactiveManager() {
    LoadLastSeen();
}

void ProactiveManager::SaveLastSeen() {
    cJSON* root = cJSON_CreateObject();
    for (auto& kv : last_seen_) {
        cJSON_AddNumberToObject(root, kv.first.c_str(), (double)kv.second);
    }
    char* str = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!str) return;
    Settings s("faces", true);
    s.SetString("last_seen", str);
    free(str);
    ESP_LOGI(TAG, "SaveLastSeen: %zu entries", last_seen_.size());
}

void ProactiveManager::LoadLastSeen() {
    Settings s("faces", false);
    std::string json = s.GetString("last_seen", "");
    if (json.empty()) return;
    cJSON* root = cJSON_Parse(json.c_str());
    if (!root) return;
    cJSON* item = nullptr;
    cJSON_ArrayForEach(item, root) {
        if (item->string && cJSON_IsNumber(item)) {
            last_seen_[item->string] = (time_t)item->valuedouble;
        }
    }
    cJSON_Delete(root);
    ESP_LOGI(TAG, "LoadLastSeen: %zu entries", last_seen_.size());
}

std::string ProactiveManager::ResolveFaceId(const std::string& result) {
    // TODO: 接入人脸识别后，IsFaceDbEmpty() 改为查询真实数据库
    // 当前阶段始终返回 "default"（家庭共享模式）
    if (result.empty() || result == "no_face") {
        return "default";
    }
    if (result == "unknown") {
        return "guest";
    }
    return result;
}

std::vector<ProactiveManager::BriefItem> ProactiveManager::GetPendingItems(
    const std::string& face_id, int away_seconds) {

    if (face_id == "guest") return {};
    if (away_seconds < 180) return {};

    std::lock_guard<std::mutex> lock(mutex_);

    std::vector<BriefItem> result;
    time_t now = time(nullptr);
    struct tm t;
    localtime_r(&now, &t);
    int cur_total_min = t.tm_hour * 60 + t.tm_min;

    // 收集该用户可见的闹钟（enabled 且未送达、未过时的）
    for (auto& a : AlarmManager::GetInstance().GetAll(face_id)) {
        if (!a.enabled) continue;
        std::string key = "alarm:" + std::to_string(a.id);
        if (delivered_.count(face_id) && delivered_[face_id].count(key)) continue;
        int alarm_min = a.hour * 60 + a.minute;
        if (alarm_min <= cur_total_min) continue;
        char time_buf[16];
        snprintf(time_buf, sizeof(time_buf), "%02d:%02d", a.hour, a.minute);
        result.push_back({"alarm", a.id, std::string(time_buf) + " " + a.label});
    }

    // 收集该用户可见的习惯（enabled 且未送达的）
    for (auto& h : HabitManager::GetInstance().GetAll(face_id)) {
        if (!h.enabled) continue;
        std::string key = "habit:" + std::to_string(h.id);
        if (delivered_.count(face_id) && delivered_[face_id].count(key)) continue;
        char time_buf[16];
        snprintf(time_buf, sizeof(time_buf), "%02d:%02d", h.hour, h.minute);
        result.push_back({"habit", h.id, std::string(time_buf) + " " + h.description});
    }

    // 收集该用户可见的备忘录
    for (auto& n : NoteManager::GetInstance().GetAll(face_id)) {
        std::string key = "note:" + std::to_string(n.id);
        if (delivered_.count(face_id) && delivered_[face_id].count(key)) continue;

        if (n.fired && n.remind_at > 0) {
            uint32_t now_ts = (uint32_t)now;
            if (now_ts > n.remind_at + NoteManager::kFiredExpirySec) continue;
        }

        std::string desc = n.text;
        if (n.fired) {
            desc = n.text + "（已提醒，待确认）";
        } else if (n.remind_at > 0) {
            time_t rt = (time_t)n.remind_at;
            struct tm rtm;
            localtime_r(&rt, &rtm);
            char tbuf[16];
            snprintf(tbuf, sizeof(tbuf), "%02d:%02d", rtm.tm_hour, rtm.tm_min);
            desc = std::string(tbuf) + " " + n.text;
        }
        result.push_back({"note", n.id, desc});
    }

    // 短时间离开（3~20min）：只保留离开期间应触发的事项
    if (away_seconds < 1200 && !result.empty()) {
        int absent_start_min = cur_total_min - (away_seconds / 60);
        if (absent_start_min < 0) absent_start_min = 0;
        std::vector<BriefItem> filtered;
        for (auto& item : result) {
            if (item.type == "alarm") {
                auto alarms = AlarmManager::GetInstance().GetAll();
                for (auto& a : alarms) {
                    if (a.id == item.id) {
                        int alarm_min = a.hour * 60 + a.minute;
                        if (alarm_min >= absent_start_min && alarm_min <= cur_total_min) {
                            filtered.push_back(item);
                        }
                        break;
                    }
                }
            } else if (item.type == "habit") {
                auto habits = HabitManager::GetInstance().GetAll();
                for (auto& h : habits) {
                    if (h.id == item.id) {
                        int trigger_min = h.hour * 60 + h.minute - h.advance_minutes;
                        if (trigger_min >= absent_start_min && trigger_min <= cur_total_min) {
                            filtered.push_back(item);
                        }
                        break;
                    }
                }
            } else if (item.type == "note") {
                // 备忘录无精确时间窗口判断，短时间离开时也包含
                filtered.push_back(item);
            }
        }
        return filtered;
    }

    return result;
}

void ProactiveManager::MarkDelivered(const std::string& face_id, const std::string& key) {
    std::lock_guard<std::mutex> lock(mutex_);
    delivered_[face_id].insert(key);
    ESP_LOGI(TAG, "Delivered: [%s] %s", face_id.c_str(), key.c_str());
}

bool ProactiveManager::IsDelivered(const std::string& face_id, const std::string& key) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!delivered_.count(face_id)) return false;
    return delivered_[face_id].count(key) > 0;
}

void ProactiveManager::MarkCompleted(const std::string& face_id, const std::string& key) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (delivered_.count(face_id)) {
        delivered_[face_id].erase(key);
    }
    ESP_LOGI(TAG, "Completed: [%s] %s", face_id.c_str(), key.c_str());

    // 备忘录完成后直接删除（不需要等自动清理）
    if (key.rfind("note:", 0) == 0) {
        int id = std::stoi(key.substr(5));
        NoteManager::GetInstance().Delete(id);
        ESP_LOGI(TAG, "Note id=%d deleted on completion", id);
    }
}

void ProactiveManager::UpdateLastSeen(const std::string& face_id, time_t t) {
    std::lock_guard<std::mutex> lock(mutex_);
    last_seen_[face_id] = t;
    SaveLastSeen();
}

time_t ProactiveManager::GetLastSeen(const std::string& face_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (last_seen_.count(face_id)) {
        return last_seen_[face_id];
    }
    return 0;
}

void ProactiveManager::AddMissedReminder(const std::string& owner,
                                          const std::string& type,
                                          int id, const std::string& text) {
    std::lock_guard<std::mutex> lock(mutex_);
    MissedReminder mr;
    mr.owner    = owner;
    mr.type     = type;
    mr.id       = id;
    mr.text     = text;
    mr.fired_at = time(nullptr);
    missed_reminders_[owner].push_back(mr);
    ESP_LOGI(TAG, "MissedReminder queued: [%s] %s:%d %s",
             owner.c_str(), type.c_str(), id, text.c_str());
}

std::vector<ProactiveManager::MissedReminder>
ProactiveManager::PopMissedReminders(const std::string& face_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = missed_reminders_.find(face_id);
    if (it == missed_reminders_.end()) return {};
    auto result = std::move(it->second);
    missed_reminders_.erase(it);
    ESP_LOGI(TAG, "PopMissedReminders: [%s] %zu items", face_id.c_str(), result.size());
    return result;
}

bool ProactiveManager::HasMissedReminders(const std::string& face_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = missed_reminders_.find(face_id);
    return it != missed_reminders_.end() && !it->second.empty();
}

void ProactiveManager::ClearDailyState() {
    std::lock_guard<std::mutex> lock(mutex_);
    delivered_.clear();
    missed_reminders_.clear();
    ESP_LOGI(TAG, "Daily state cleared (3AM reset)");
}

void ProactiveManager::SetSensorAbsentSince(time_t t) {
    sensor_absent_since_ = t;
}

time_t ProactiveManager::GetSensorAbsentSince() const {
    return sensor_absent_since_;
}
