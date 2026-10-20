#include "behavior_logger.h"
#include <esp_log.h>
#include <esp_spiffs.h>
#include <cJSON.h>
#include <ctime>
#include <cstdio>
#include <cstring>
#include <sys/stat.h>
#include <algorithm>
#include <map>
#include <array>
#include "settings.h"
#include <functional>

namespace {
// Read complete bounded lines; an overlong line is discarded through its newline.
bool ReadLine(FILE* file, std::string& line) {
    line.clear(); bool overflow = false; int ch;
    while ((ch = fgetc(file)) != EOF) {
        if (ch == '\n') return true;
        if (line.size() < 8192 && !overflow) line.push_back(static_cast<char>(ch));
        else { overflow = true; line.clear(); }
    }
    return !line.empty();
}
std::string JsonText(cJSON* item, const char* key) {
    auto value = cJSON_GetObjectItem(item, key);
    return cJSON_IsString(value) ? value->valuestring : "";
}
uint64_t Sequence(cJSON* item) {
    const auto value = JsonText(item, "seq");
    if (value.empty()) return 0;
    char* end = nullptr; auto seq = strtoull(value.c_str(), &end, 10);
    return end && *end == 0 ? seq : 0;
}
bool RewriteLog(const std::function<bool(cJSON*)>& keep) {
    FILE* input = fopen(BehaviorLogger::kLogPath, "r");
    if (!input) return true;
    const std::string temporary = std::string(BehaviorLogger::kLogPath) + ".tmp";
    const std::string backup = std::string(BehaviorLogger::kLogPath) + ".bak";
    FILE* output = fopen(temporary.c_str(), "w");
    if (!output) { fclose(input); return false; }
    bool okay = true; std::string line;
    while (ReadLine(input, line)) {
        auto item = cJSON_Parse(line.c_str());
        // Legacy records without trustworthy ownership are not imported.
        if (item && !JsonText(item, "person").empty() && Sequence(item) && keep(item)) {
            if (fprintf(output, "%s\n", line.c_str()) < 0) okay = false;
        }
        cJSON_Delete(item);
    }
    fclose(input); if (fclose(output) != 0) okay = false;
    if (!okay) { remove(temporary.c_str()); return false; }
    remove(backup.c_str());
    if (rename(BehaviorLogger::kLogPath, backup.c_str()) != 0) return false;
    if (rename(temporary.c_str(), BehaviorLogger::kLogPath) != 0) {
        rename(backup.c_str(), BehaviorLogger::kLogPath); return false;
    }
    remove(backup.c_str()); return true;
}
}

#define TAG "BehaviorLogger"

bool BehaviorLogger::Init() {
    esp_vfs_spiffs_conf_t conf = {
        .base_path            = kMountPoint,
        .partition_label      = kPartitionLabel,  // 明确指定，不会碰 assets 分区
        .max_files            = 4,
        .format_if_mount_failed = true,           // 首次使用时格式化（新建空分区）
    };
    esp_err_t ret = esp_vfs_spiffs_register(&conf);
    if (ret != ESP_OK && ret != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "Mount failed: %s", esp_err_to_name(ret));
        return false;
    }
    // 确保日志目录存在
    struct stat st;
    if (stat(kLogDir, &st) != 0) {
        mkdir(kLogDir, 0755);
    }
    ESP_LOGI(TAG, "userdata SPIFFS mounted at %s", kMountPoint);
    const std::string backup = std::string(kLogPath) + ".bak";
    if (stat(kLogPath, &st) != 0 && stat(backup.c_str(), &st) == 0)
        rename(backup.c_str(), kLogPath);
    return true;
}

void BehaviorLogger::ClearLog() {
    ESP_LOGW(TAG, "Whole-device clear disabled; person watermark required");
}

bool BehaviorLogger::IsLogFull() const {
    std::lock_guard<std::mutex> lock(mutex_);
    struct stat st;
    if (stat(kLogPath, &st) != 0) return false;
    return (size_t)st.st_size >= kMaxLogSize;
}

bool BehaviorLogger::Log(const std::string& intent, const std::string& raw,
                          int hour, int minute, const std::string& outcome, std::string* record) {
    if (!bound_person_turn || !bound_person_turn->Eligible()) return false;
    std::lock_guard<std::mutex> lock(mutex_);

    // 写入前检查文件大小，超限时标记需要触发分析+清理
    // 实际触发由 application.cc 的 IsLogFull() 检查完成，这里只做防御性截断
    {
        struct stat st;
        if (stat(kLogPath, &st) == 0 && (size_t)st.st_size >= kMaxLogSize) {
            ESP_LOGW(TAG, "Log full (%d bytes), dropping entry until analyzed",
                     (int)st.st_size);
            return false;
        }
    }

    uint32_t ts = (uint32_t)time(nullptr);
    cJSON* item = cJSON_CreateObject();
    Settings sequence_settings("behavior_seq", true);
    std::string next;
    auto sequence_status = sequence_settings.TryGetString("next", &next);
    if (sequence_status == Settings::ReadStatus::Error) { cJSON_Delete(item); return false; }
    if (sequence_status == Settings::ReadStatus::NotFound) next = "1";
    char* sequence_end = nullptr;
    uint64_t sequence = strtoull(next.c_str(), &sequence_end, 10);
    if (next.empty() || !sequence_end || *sequence_end || next[0] == '-') { cJSON_Delete(item); return false; }
    if (!sequence || sequence == UINT64_MAX) { cJSON_Delete(item); return false; }
    // Reserve before append: a reboot cannot reuse an acknowledged sequence.
    if (sequence_settings.SetString("next", std::to_string(sequence + 1)) != ESP_OK || sequence_settings.Commit() != ESP_OK) { cJSON_Delete(item); return false; }
    cJSON_AddStringToObject(item, "seq", std::to_string(sequence).c_str());
    cJSON_AddStringToObject(item, "person", bound_person_turn->person_id.c_str());
    cJSON_AddStringToObject(item, "turn", bound_person_turn->turn_id.c_str());
    cJSON_AddStringToObject(item, "event", (bound_person_turn->turn_id + ":" + std::to_string(sequence)).c_str());
    cJSON_AddStringToObject(item, "generation", std::to_string(bound_person_turn->generation).c_str());
    cJSON_AddStringToObject(item, "account", bound_person_turn->account_id.c_str());
    cJSON_AddStringToObject(item, "directory_version", std::to_string(bound_person_turn->directory_version).c_str());
    cJSON_AddStringToObject(item, "voiceprint_id", bound_person_turn->voiceprint_id.c_str());
    cJSON_AddStringToObject(item, "template_version", std::to_string(bound_person_turn->template_version).c_str());
    cJSON_AddStringToObject(item, "outcome", Utf8Prefix(outcome, 32).c_str());
    cJSON_AddNumberToObject(item, "ts",     (double)ts);
    cJSON_AddNumberToObject(item, "hour",   hour);
    cJSON_AddNumberToObject(item, "minute", minute);
    cJSON_AddStringToObject(item, "intent", Utf8Prefix(intent, 64).c_str());
    cJSON_AddStringToObject(item, "raw",    Utf8Prefix(raw, 512).c_str());
    char* line = cJSON_PrintUnformatted(item);
    cJSON_Delete(item);
    if (!line) return false;

    FILE* f = fopen(kLogPath, "a");
    bool written = false;
    if (f) {
        written = fprintf(f, "%s\n", line) > 0;
        if (fclose(f) != 0) written = false;
        ESP_LOGD(TAG, "Logged: intent=%s %d:%02d", intent.c_str(), hour, minute);
    } else {
        ESP_LOGW(TAG, "Cannot open log file: %s", kLogPath);
    }
    if (written && record) *record = line;
    free(line);
    return written;
}

std::string BehaviorLogger::ReadAll() {
    std::lock_guard<std::mutex> lock(mutex_);
    FILE* f = fopen(kLogPath, "r");
    if (!f) return "";
    std::string result;
    char buf[256];
    while (fgets(buf, sizeof(buf), f)) {
        result += buf;
    }
    fclose(f);
    return result;
}

std::string BehaviorLogger::Export(const std::string& person, uint64_t after, size_t limit) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto envelope = cJSON_CreateObject();
    auto rows = cJSON_AddArrayToObject(envelope, "records");
    FILE* input = fopen(kLogPath, "r");
    uint64_t cursor = after; size_t count = 0; std::string line;
    bool more = false;
    if (input) {
        while (ReadLine(input, line)) {
            auto item = cJSON_Parse(line.c_str());
            if (!item || JsonText(item, "person") != person || Sequence(item) <= after) {
                cJSON_Delete(item); continue;
            }
            if (count >= std::min(limit, size_t(10))) { more = true; cJSON_Delete(item); break; }
            cursor = std::max(cursor, Sequence(item)); ++count;
            cJSON_AddItemToArray(rows, item);
        }
        fclose(input);
    }
    cJSON_AddStringToObject(envelope, "cursor", std::to_string(cursor).c_str());
    cJSON_AddBoolToObject(envelope, "more", more);
    char* encoded = cJSON_PrintUnformatted(envelope);
    std::string result = encoded ? encoded : "{}";
    cJSON_free(encoded); cJSON_Delete(envelope); return result;
}

void BehaviorLogger::Prune() {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto cutoff = time(nullptr) - kRetentionDays * 86400;
    RewriteLog([cutoff](cJSON* item) {
        auto timestamp = cJSON_GetObjectItem(item, "ts");
        return cJSON_IsNumber(timestamp) && timestamp->valuedouble >= cutoff;
    });
}

bool BehaviorLogger::Acknowledge(const std::string& person, uint64_t watermark) {
    if (person.empty() || !watermark) return false;
    std::lock_guard<std::mutex> lock(mutex_);
    return RewriteLog([&](cJSON* item) { return JsonText(item, "person") != person || Sequence(item) > watermark; });
}
bool BehaviorLogger::RetirePerson(const std::string& person) {
    if (person.empty()) return false;
    std::lock_guard<std::mutex> lock(mutex_);
    return RewriteLog([&](cJSON* item) { return JsonText(item, "person") != person; });
}

std::vector<HourSummary> BehaviorLogger::Summarize(const std::string& person, uint64_t* watermark) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (watermark) *watermark = 0;
    if (person.empty()) return {};

    // 计算7天前的时间戳
    time_t now = time(nullptr);
    uint32_t cutoff = (uint32_t)(now - (uint32_t)kAnalysisDays * 86400);

    // 按小时分桶：hour -> day_index(0~6) -> 该天该小时的所有 raw 原话
    // day_index = (ts - cutoff) / 86400，范围 0~6
    struct DayBucket {
        std::vector<std::string> raws;
    };
    // hour(0~23) -> array of 7 days
    std::map<int, std::array<DayBucket, 7>> buckets;

    FILE* f = fopen(kLogPath, "r");
    if (!f) return {};

    std::string line;
    while (ReadLine(f, line)) {
        cJSON* item = cJSON_Parse(line.c_str());
        if (!item) continue;
        if (JsonText(item, "person") != person || !Sequence(item)) { cJSON_Delete(item); continue; }
        cJSON* jts   = cJSON_GetObjectItem(item, "ts");
        cJSON* jhour = cJSON_GetObjectItem(item, "hour");
        cJSON* jraw  = cJSON_GetObjectItem(item, "raw");
        if (!jts || !jhour || !jraw || !cJSON_IsString(jraw)) {
            cJSON_Delete(item);
            continue;
        }
        uint32_t ts = (uint32_t)jts->valueint;
        if (ts < cutoff) { cJSON_Delete(item); continue; }
        if (watermark) *watermark = std::max(*watermark, Sequence(item));

        int hour = jhour->valueint;
        if (hour < 0 || hour > 23) { cJSON_Delete(item); continue; }

        // Include the current day, rather than dropping records at exactly now.
        int day_idx = kAnalysisDays - 1 - static_cast<int>((now - ts) / 86400);
        if (day_idx < 0 || day_idx >= kAnalysisDays) { cJSON_Delete(item); continue; }

        buckets[hour][day_idx].raws.push_back(jraw->valuestring);
        cJSON_Delete(item);
    }
    fclose(f);

    // 分析每个小时，找出规律时间段
    std::vector<HourSummary> result;
    for (auto& [hour, days] : buckets) {
        int days_active = 0;
        int total_count = 0;
        for (int d = 0; d < kAnalysisDays; d++) {
            if (!days[d].raws.empty()) {
                days_active++;
                total_count += (int)days[d].raws.size();
            }
        }
        // 规律判定
        if (days_active < kMinActiveDays || total_count < kMinTotalCount) continue;

        HourSummary summary;
        summary.hour        = hour;
        summary.days_active = days_active;
        summary.total_count = total_count;

        // 每天取最长的 kSamplesPerDay 条原话
        for (int d = 0; d < kAnalysisDays; d++) {
            auto& raws = days[d].raws;
            if (raws.empty()) {
                summary.samples.push_back({});
                continue;
            }
            // 按字符串长度降序排序，取前 kSamplesPerDay 条
            std::sort(raws.begin(), raws.end(),
                      [](const std::string& a, const std::string& b) {
                          return a.size() > b.size();
                      });
            std::vector<std::string> top;
            for (int i = 0; i < kSamplesPerDay && i < (int)raws.size(); i++) {
                top.push_back(raws[i]);
            }
            summary.samples.push_back(top);
        }
        result.push_back(summary);
        ESP_LOGI(TAG, "Summarize: hour=%d days_active=%d total=%d",
                 hour, days_active, total_count);
    }
    return result;
}
