#include "reminder_coordinator.h"

#include "alarm_manager.h"
#include "application.h"
#include "assets/lang_config.h"
#include "board.h"
#include "display/display.h"
#include "habit_manager.h"
#include "identity_client.h"
#include "mcp_tools/mcp_permission.h"
#include "note_manager.h"
#include "presence_context.h"
#include "proactive_wake_coordinator.h"
#include "face_roster.h"
#include "reminder_control_client.h"
#include "reminder_identity_verifier.h"
#include "reminder_voice_service.h"
#include "test_observability.h"
#include "user_context.h"
#include "person_directory.h"

#include <cJSON.h>
#include <esp_log.h>

#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <dirent.h>
#include <sys/stat.h>

namespace {

constexpr const char* kTag = "ReminderCoordinator";
constexpr const char* kStorePath = "/userdata/reminders.json";
constexpr const char* kStoreTempPath = "/userdata/reminders.tmp";
constexpr const char* kStoreBackupPath = "/userdata/reminders.bak";
constexpr size_t kMaxInstances = 32;
// The same budget gates every new store write and every normal store read.
// A one-time larger legacy read is accepted only so older unbounded stores can
// be compacted instead of being silently discarded.
constexpr size_t kReminderStoreBudgetBytes = 32 * 1024;
constexpr size_t kLegacyStoreReadLimitBytes = 64 * 1024;
constexpr size_t kMaxPersistedVoiceAssetsPerInstance = 2;
constexpr time_t kIdentityRetrySeconds = 20;
constexpr time_t kAlarmRepeatSeconds = 3 * 60;
constexpr time_t kAlarmAttentionWindowSeconds = 60 * 60;
constexpr time_t kCardInteractionWindowSeconds = 180;
constexpr time_t kMaxExplicitSnoozeSeconds = 365 * 24 * 60 * 60;

bool ResolveSnoozeAt(time_t now, int minutes, time_t requested_snooze_at,
                     time_t& snooze_at, int& delay_minutes) {
    if (requested_snooze_at > 0) {
        const time_t delay = requested_snooze_at - now;
        if (delay <= 0 || delay > kMaxExplicitSnoozeSeconds) return false;
        snooze_at = requested_snooze_at;
        delay_minutes = static_cast<int>((delay + 59) / 60);
        return true;
    }

    const int delay = minutes == 0 ? 15 : minutes;
    if (delay < 1 || delay > 60) return false;
    snooze_at = now + delay * 60;
    delay_minutes = delay;
    return true;
}

ReminderSourceType ParseSourceType(const char* value) {
    if (value && std::strcmp(value, "alarm") == 0) return ReminderSourceType::kAlarm;
    if (value && std::strcmp(value, "note") == 0) return ReminderSourceType::kNote;
    if (value && std::strcmp(value, "habit") == 0) return ReminderSourceType::kHabit;
    return ReminderSourceType::kInformation;
}

ReminderPriority ParsePriority(const char* value) {
    if (value && std::strcmp(value, "high") == 0) return ReminderPriority::kHigh;
    if (value && std::strcmp(value, "normal") == 0) return ReminderPriority::kNormal;
    return ReminderPriority::kLow;
}

ReminderStatus ParseStatus(const char* value) {
    if (!value) return ReminderStatus::kQueued;
    if (std::strcmp(value, "pending") == 0) return ReminderStatus::kPending;
    if (std::strcmp(value, "queued") == 0) return ReminderStatus::kQueued;
    if (std::strcmp(value, "waiting_presence") == 0) {
        return ReminderStatus::kWaitingPresence;
    }
    if (std::strcmp(value, "verifying_identity") == 0) {
        return ReminderStatus::kVerifyingIdentity;
    }
    if (std::strcmp(value, "waiting_recipient") == 0) {
        return ReminderStatus::kWaitingRecipient;
    }
    if (std::strcmp(value, "presenting") == 0) return ReminderStatus::kPresenting;
    if (std::strcmp(value, "snoozed") == 0) return ReminderStatus::kSnoozed;
    if (std::strcmp(value, "attention_silenced") == 0) return ReminderStatus::kAttentionSilenced;
    if (std::strcmp(value, "awaiting_undo") == 0) return ReminderStatus::kAwaitingUndo;
    if (std::strcmp(value, "completed") == 0) return ReminderStatus::kCompleted;
    if (std::strcmp(value, "skipped") == 0) return ReminderStatus::kSkipped;
    if (std::strcmp(value, "dismissed") == 0) return ReminderStatus::kDismissed;
    return ReminderStatus::kExpired;
}

std::string ActionName(ReminderAction action) {
    switch (action) {
        case ReminderAction::kPrimary: return "primary";
        case ReminderAction::kSecondary: return "secondary";
        case ReminderAction::kTertiary: return "tertiary";
        case ReminderAction::kCancel: return "cancel";
        case ReminderAction::kSilenceAttention: return "silence";
        case ReminderAction::kUndo: return "undo";
    }
    return "unknown";
}

void AddString(cJSON* object, const char* key, const std::string& value) {
    cJSON_AddStringToObject(object, key, value.c_str());
}

std::string JsonString(cJSON* object, const char* key,
                       const std::string& fallback = "") {
    cJSON* value = cJSON_GetObjectItemCaseSensitive(object, key);
    return cJSON_IsString(value) && value->valuestring
        ? value->valuestring : fallback;
}

std::string JsonStringCompat(
    cJSON* object, const char* compact_key, const char* legacy_key,
    const std::string& fallback = "") {
    cJSON* value =
        cJSON_GetObjectItemCaseSensitive(object, compact_key);
    if (!cJSON_IsString(value)) {
        value = cJSON_GetObjectItemCaseSensitive(
            object, legacy_key);
    }
    return cJSON_IsString(value) && value->valuestring
        ? value->valuestring : fallback;
}

int64_t JsonInt64Compat(
    cJSON* object, const char* compact_key, const char* legacy_key,
    int64_t fallback = 0) {
    cJSON* value =
        cJSON_GetObjectItemCaseSensitive(object, compact_key);
    if (!cJSON_IsNumber(value)) {
        value = cJSON_GetObjectItemCaseSensitive(
            object, legacy_key);
    }
    return cJSON_IsNumber(value)
        ? static_cast<int64_t>(value->valuedouble) : fallback;
}

ReminderActionPolicy PolicyFor(ReminderSourceType type) {
    ReminderActionPolicy policy;
    switch (type) {
        case ReminderSourceType::kAlarm:
            policy.primary_label = "完成";
            policy.secondary_label = "稍后";
            policy.tertiary_label = "不需要了";
            policy.default_snooze_minutes = 15;
            break;
        case ReminderSourceType::kNote:
            policy.primary_label = "完成";
            policy.secondary_label = "稍后";
            policy.tertiary_label = "今天跳过";
            policy.default_snooze_minutes = 15;
            break;
        case ReminderSourceType::kHabit:
            policy.primary_label = "完成";
            policy.secondary_label = "稍后";
            policy.tertiary_label = "今天跳过";
            policy.default_snooze_minutes = 15;
            break;
        case ReminderSourceType::kInformation:
            break;
    }
    return policy;
}

bool SourceExists(const ReminderInstance& instance) {
    if (instance.source_type == ReminderSourceType::kInformation) return true;
    if (instance.source_type == ReminderSourceType::kAlarm) {
        for (const auto& item : AlarmManager::GetInstance().GetAll()) {
            if (item.id == instance.source_id &&
                item.owner_user_id == instance.owner_user_id) return true;
        }
    } else if (instance.source_type == ReminderSourceType::kNote) {
        for (const auto& item : NoteManager::GetInstance().GetAll()) {
            if (item.id == instance.source_id &&
                item.owner_user_id == instance.owner_user_id) return true;
        }
    } else if (instance.source_type == ReminderSourceType::kHabit) {
        for (const auto& item : HabitManager::GetInstance().GetAll()) {
            // A management deletion stops queued/deferred occurrences too.
            if (!item.sync_id.empty() && !item.enabled) continue;
            if (item.id == instance.source_id &&
                item.owner_user_id == instance.owner_user_id) return true;
        }
    }
    return false;
}

std::vector<std::string> SplitDetails(const std::string& text) {
    std::vector<std::string> result;
    size_t start = 0;
    while (start <= text.size() && result.size() < 4) {
        size_t end = text.find('\n', start);
        std::string line = text.substr(
            start, end == std::string::npos ? std::string::npos : end - start);
        if (!line.empty()) result.push_back(line);
        if (end == std::string::npos) break;
        start = end + 1;
    }
    return result;
}

bool IsActiveStatus(ReminderStatus status) {
    return status == ReminderStatus::kPending ||
           status == ReminderStatus::kQueued ||
           status == ReminderStatus::kWaitingPresence ||
           status == ReminderStatus::kVerifyingIdentity ||
           status == ReminderStatus::kWaitingRecipient ||
           status == ReminderStatus::kPresenting ||
           status == ReminderStatus::kSnoozed ||
           status == ReminderStatus::kAttentionSilenced ||
           status == ReminderStatus::kAwaitingUndo;
}

bool IsDeliveryGateStatus(ReminderStatus status) {
    return status == ReminderStatus::kQueued ||
           status == ReminderStatus::kWaitingPresence ||
           status == ReminderStatus::kVerifyingIdentity ||
           status == ReminderStatus::kWaitingRecipient;
}

int VoicePhaseRetentionRank(const ReminderInstance& instance,
                            const ReminderVoiceAsset& asset) {
    int rank = asset.cached ? 0 : 20;
    if (asset.phase == "due") return rank;
    if (instance.status == ReminderStatus::kSnoozed &&
        asset.phase == "snooze") return rank + 2;
    if (asset.phase == "repeat") return rank + 3;
    if (asset.phase == "pre_alert") return rank + 4;
    if (asset.phase == "completion") return rank + 10;
    if (asset.phase == "skip") return rank + 11;
    return rank + 19;
}

// Returns cache paths dropped from this instance's metadata. Callers that own
// the live instance list must delete a path only when no other instance still
// references it.
std::vector<std::string> CompactVoiceMetadata(
    ReminderInstance& instance) {
    std::vector<std::string> dropped_paths;
    auto remember_drop = [&](const ReminderVoiceAsset& asset) {
        if (asset.cached && !asset.cache_path.empty() &&
            std::find(dropped_paths.begin(), dropped_paths.end(),
                      asset.cache_path) == dropped_paths.end()) {
            dropped_paths.push_back(asset.cache_path);
        }
    };
    auto keep = instance.voice_assets.begin();
    for (auto it = instance.voice_assets.begin();
         it != instance.voice_assets.end(); ++it) {
        if (it->voice_revision != instance.voice_revision) {
            remember_drop(*it);
            continue;
        }
        if (keep != it) *keep = std::move(*it);
        ++keep;
    }
    instance.voice_assets.erase(keep, instance.voice_assets.end());
    std::stable_sort(
        instance.voice_assets.begin(), instance.voice_assets.end(),
        [&](const ReminderVoiceAsset& left,
            const ReminderVoiceAsset& right) {
            return VoicePhaseRetentionRank(instance, left) <
                   VoicePhaseRetentionRank(instance, right);
        });
    if (instance.voice_assets.size() >
        kMaxPersistedVoiceAssetsPerInstance) {
        for (size_t index = kMaxPersistedVoiceAssetsPerInstance;
             index < instance.voice_assets.size(); ++index) {
            remember_drop(instance.voice_assets[index]);
        }
        instance.voice_assets.resize(
            kMaxPersistedVoiceAssetsPerInstance);
    }

    instance.pre_alert_script.clear();
    instance.due_script.clear();
    instance.repeat_script.clear();
    instance.completion_script.clear();
    instance.snooze_script.clear();
    instance.skip_script.clear();
    for (const auto& asset : instance.voice_assets) {
        if (asset.phase == "pre_alert") {
            instance.pre_alert_script = asset.script;
        } else if (asset.phase == "due") {
            instance.due_script = asset.script;
        } else if (asset.phase == "repeat") {
            instance.repeat_script = asset.script;
        } else if (asset.phase == "completion") {
            instance.completion_script = asset.script;
        } else if (asset.phase == "snooze") {
            instance.snooze_script = asset.script;
        } else if (asset.phase == "skip") {
            instance.skip_script = asset.script;
        }
    }
    return dropped_paths;
}

bool RemoveUnreferencedCachePaths(
    const std::vector<ReminderInstance>& instances,
    const std::vector<std::string>& candidates) {
    for (const auto& path : candidates) {
        if (path.empty()) continue;
        bool referenced = false;
        for (const auto& instance : instances) {
            referenced = std::any_of(
                instance.voice_assets.begin(),
                instance.voice_assets.end(),
                [&](const ReminderVoiceAsset& asset) {
                    return asset.cached && asset.cache_path == path;
                });
            if (referenced) break;
        }
        if (!referenced && std::remove(path.c_str()) != 0 && errno != ENOENT) return false;
    }
    return true;
}

void TruncateUtf8(std::string& value, size_t max_bytes) {
    if (value.size() <= max_bytes) return;
    size_t end = max_bytes;
    while (end > 0 &&
           (static_cast<unsigned char>(value[end]) & 0xc0u) ==
               0x80u) {
        --end;
    }
    value.resize(end);
}

void CompactPersistedText(ReminderInstance& instance) {
    // Display prose is bounded before persistence so it can never crowd out
    // identity, ownership, timing, status, action, or undo state.
    TruncateUtf8(instance.occurrence_key, 96);
    TruncateUtf8(instance.attention_policy, 32);
    TruncateUtf8(instance.title, 96);
    TruncateUtf8(instance.detail, 256);
    TruncateUtf8(instance.pending_final_action, 32);
    TruncateUtf8(instance.last_action, 32);
}

cJSON* SerializeInstance(const ReminderInstance& instance) {
    cJSON* item = cJSON_CreateObject();
    AddString(item, "id", instance.instance_id);
    AddString(item, "ok", instance.occurrence_key);
    AddString(item, "src",
              ReminderCoordinator::SourceTypeName(instance.source_type));
    cJSON_AddNumberToObject(item, "sid", instance.source_id);
    AddString(item, "uid", instance.owner_user_id);
    AddString(item, "cid", instance.creator_person_id);
    AddString(item, "rid", instance.recipient_person_id);
    AddString(item, "rds", instance.recipient_display_name_snapshot);
    cJSON_AddBoolToObject(item, "unb", instance.delivery_unbound);
    cJSON_AddNumberToObject(
        item, "dpg", instance.delivery_presence_generation);
    AddString(item, "lvp", instance.last_verified_person_id);
    cJSON_AddNumberToObject(
        item, "lda", static_cast<double>(instance.last_delivery_attempt_at));
    cJSON_AddNumberToObject(
        item, "nir", static_cast<double>(instance.next_identity_retry_at));
    cJSON_AddNumberToObject(item, "rac", instance.reattention_count);
    cJSON_AddBoolToObject(item, "uce", instance.unattended_chime_emitted);
    cJSON_AddNumberToObject(item, "ppg", instance.prompted_presence_generation);
    cJSON_AddNumberToObject(item, "dpg2", instance.deferred_presence_generation);
    AddString(item, "pri",
              ReminderCoordinator::PriorityName(instance.priority));
    AddString(item, "ap", instance.attention_policy);
    cJSON_AddNumberToObject(item, "due",
                            static_cast<double>(instance.due_at));
    cJSON_AddNumberToObject(item, "pre",
                            static_cast<double>(instance.pre_alert_at));
    cJSON_AddNumberToObject(item, "next",
                            static_cast<double>(instance.next_attention_at));
    cJSON_AddNumberToObject(item, "rep", instance.repeat_count);
    AddString(item, "st",
              ReminderCoordinator::StatusName(instance.status));
    cJSON_AddNumberToObject(item, "rev", instance.revision);
    cJSON_AddNumberToObject(
        item, "vr", instance.voice_revision);
    cJSON_AddNumberToObject(
        item, "vrr", instance.voice_request_revision);
    cJSON_AddNumberToObject(
        item, "vra", static_cast<double>(instance.voice_request_at));
    AddString(item, "ti", instance.title);
    AddString(item, "de", instance.detail);
    cJSON_AddNumberToObject(item, "cr",
                            static_cast<double>(instance.created_at));
    cJSON_AddNumberToObject(item, "up",
                            static_cast<double>(instance.updated_at));
    cJSON_AddNumberToObject(item, "lp",
                            static_cast<double>(instance.last_presented_at));
    cJSON_AddNumberToObject(item, "ce",
                            static_cast<double>(instance.card_expires_at));
    cJSON_AddNumberToObject(item, "aas",
                            static_cast<double>(instance.alarm_attention_started_at));
    cJSON_AddBoolToObject(item, "mis", instance.missed);
    cJSON_AddBoolToObject(item, "vd", instance.voice_deferred);
    cJSON_AddNumberToObject(
        item, "asu",
        static_cast<double>(instance.attention_silenced_until));
    cJSON_AddNumberToObject(item, "ud",
                            static_cast<double>(instance.undo_deadline));
    AddString(item, "pfa",
              instance.pending_final_action);
    AddString(item, "la", instance.last_action);
    cJSON* assets = cJSON_CreateArray();
    for (const auto& asset : instance.voice_assets) {
        cJSON* asset_json = cJSON_CreateObject();
        AddString(asset_json, "ph", asset.phase);
        AddString(asset_json, "sc", asset.script);
        AddString(asset_json, "u", asset.url);
        AddString(asset_json, "sh", asset.sha256);
        AddString(asset_json, "f", asset.format);
        AddString(asset_json, "cp", asset.cache_path);
        cJSON_AddNumberToObject(
            asset_json, "b", asset.byte_count);
        cJSON_AddBoolToObject(asset_json, "c", asset.cached);
        cJSON_AddNumberToObject(
            asset_json, "vr", asset.voice_revision);
        cJSON_AddItemToArray(assets, asset_json);
    }
    cJSON_AddItemToObject(item, "va", assets);
    return item;
}

std::string SerializeStore(
    const std::vector<ReminderInstance>& instances) {
    cJSON* root = cJSON_CreateObject();
    cJSON_AddNumberToObject(root, "v", 2);
    cJSON* array = cJSON_CreateArray();
    for (const auto& instance : instances) {
        cJSON_AddItemToArray(array, SerializeInstance(instance));
    }
    cJSON_AddItemToObject(root, "items", array);
    char* text = cJSON_PrintUnformatted(root);
    std::string result = text ? text : "";
    if (text) cJSON_free(text);
    cJSON_Delete(root);
    return result;
}

}  // namespace

ReminderCoordinator& ReminderCoordinator::GetInstance() {
    static ReminderCoordinator instance;
    return instance;
}

const char* ReminderCoordinator::SourceTypeName(ReminderSourceType type) {
    switch (type) {
        case ReminderSourceType::kAlarm: return "alarm";
        case ReminderSourceType::kNote: return "note";
        case ReminderSourceType::kHabit: return "habit";
        case ReminderSourceType::kInformation: return "information";
    }
    return "information";
}

const char* ReminderCoordinator::StatusName(ReminderStatus status) {
    switch (status) {
        case ReminderStatus::kPending: return "pending";
        case ReminderStatus::kQueued: return "queued";
        case ReminderStatus::kWaitingPresence: return "waiting_presence";
        case ReminderStatus::kVerifyingIdentity: return "verifying_identity";
        case ReminderStatus::kWaitingRecipient: return "waiting_recipient";
        case ReminderStatus::kPresenting: return "presenting";
        case ReminderStatus::kSnoozed: return "snoozed";
        case ReminderStatus::kAttentionSilenced: return "attention_silenced";
        case ReminderStatus::kAwaitingUndo: return "awaiting_undo";
        case ReminderStatus::kCompleted: return "completed";
        case ReminderStatus::kSkipped: return "skipped";
        case ReminderStatus::kDismissed: return "dismissed";
        case ReminderStatus::kExpired: return "expired";
    }
    return "expired";
}

const char* ReminderCoordinator::PriorityName(ReminderPriority priority) {
    switch (priority) {
        case ReminderPriority::kHigh: return "high";
        case ReminderPriority::kNormal: return "normal";
        case ReminderPriority::kLow: return "low";
    }
    return "low";
}

bool ReminderCoordinator::ParseAction(const std::string& value,
                                      ReminderAction& out) {
    if (value == "primary" || value == "complete" || value == "dismiss") {
        out = ReminderAction::kPrimary;
    } else if (value == "secondary" || value == "snooze" || value == "later") {
        out = ReminderAction::kSecondary;
    } else if (value == "tertiary" || value == "skip" || value == "not_needed") {
        out = ReminderAction::kTertiary;
    } else if (value == "cancel" || value == "delete") {
        out = ReminderAction::kCancel;
    } else if (value == "silence" || value == "acknowledge") {
        out = ReminderAction::kSilenceAttention;
    } else if (value == "undo") {
        out = ReminderAction::kUndo;
    } else {
        return false;
    }
    return true;
}

void ReminderCoordinator::Initialize() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (initialized_) return;
    LoadLocked();
    RecoverLocked(time(nullptr));
    SaveLocked();
    initialized_ = true;
}

bool ReminderCoordinator::IsActive(const ReminderInstance& instance) const {
    return IsActiveStatus(instance.status);
}

bool ReminderCoordinator::InvalidateMissingSourceLocked(
    ReminderInstance& instance, time_t now,
    std::string* dismiss_id, uint32_t* dismiss_rev) {
    if (!IsActive(instance) || SourceExists(instance)) return false;
    const uint32_t visual_revision = instance.revision;
    const bool is_current = current_instance_id_ == instance.instance_id;
    ESP_LOGW(kTag,
             "[REMINDER_CARD] event=source_missing instance=%s status=%s",
             instance.instance_id.c_str(), StatusName(instance.status));
    instance.status = ReminderStatus::kDismissed;
    instance.card_expires_at = 0;
    instance.updated_at = now;
    instance.last_action = "source_missing";
    AdvanceRevisionLocked(instance);
    if (is_current) {
        if (dismiss_id) *dismiss_id = instance.instance_id;
        if (dismiss_rev) *dismiss_rev = visual_revision;
        current_instance_id_.clear();
    }
    return true;
}

bool ReminderCoordinator::HasDuePersonalReminder(time_t now) const {
    std::lock_guard<std::mutex> lock(mutex_);
    for (const auto& instance : instances_) {
        if (!IsActive(instance) || !SourceExists(instance)) continue;
        if (instance.source_type == ReminderSourceType::kInformation) continue;
        if (instance.status == ReminderStatus::kSnoozed ||
            instance.status == ReminderStatus::kAttentionSilenced ||
            instance.status == ReminderStatus::kAwaitingUndo ||
            instance.status == ReminderStatus::kPresenting) {
            continue;
        }
        const bool due_or_pre_alert =
            instance.due_at <= now ||
            (instance.priority == ReminderPriority::kHigh &&
             instance.pre_alert_at > 0 && instance.pre_alert_at <= now);
        if (!due_or_pre_alert) continue;
        if (instance.status == ReminderStatus::kQueued &&
            instance.last_presented_at > 0 &&
            instance.next_attention_at > now) {
            continue;
        }
        return true;
    }
    return false;
}

void ReminderCoordinator::InvalidateVoiceAssetsLocked(
    ReminderInstance& instance) {
    std::vector<std::string> cache_paths;
    for (const auto& asset : instance.voice_assets) {
        if (asset.cached && !asset.cache_path.empty() &&
            std::find(cache_paths.begin(), cache_paths.end(),
                      asset.cache_path) == cache_paths.end()) {
            cache_paths.push_back(asset.cache_path);
        }
    }
    instance.voice_assets.clear();
    instance.pre_alert_script.clear();
    instance.due_script.clear();
    instance.repeat_script.clear();
    instance.completion_script.clear();
    instance.snooze_script.clear();
    instance.skip_script.clear();
    for (const auto& path : cache_paths) {
        bool referenced = false;
        for (const auto& candidate : instances_) {
            for (const auto& asset : candidate.voice_assets) {
                if (asset.cached && asset.cache_path == path) {
                    referenced = true;
                    break;
                }
            }
            if (referenced) break;
        }
        if (!referenced) std::remove(path.c_str());
    }
}

void ReminderCoordinator::AdvanceRevisionLocked(ReminderInstance& instance) {
    instance.revision++;
}

void ReminderCoordinator::AdvanceVoiceRevisionLocked(
    ReminderInstance& instance) {
    InvalidateVoiceAssetsLocked(instance);
    instance.voice_revision++;
    instance.voice_request_revision = 0;
    instance.voice_request_at = 0;
}

bool ReminderCoordinator::CanReadDetails(const ReminderInstance& instance,
                                         const std::string& actor) const {
    (void)instance;
    (void)actor;
    // There is no privacy-level concept: a reminder is surfaced whenever a
    // stable presence exists and the user agrees to hear the batch.
    return true;
}

bool ReminderCoordinator::RequestPendingBroadcastPrompt(
    time_t now, bool long_return, time_t away_seconds,
    const std::string& present_name) {
    Initialize();
    if (!PresenceContext::GetInstance().IsRadarPresent() ||
        Application::GetInstance().GetDeviceState() != kDeviceStateIdle) {
        return false;
    }
    if (ProactiveWakeCoordinator::GetInstance().IsIdentityOrGreetingInFlight()) {
        ESP_LOGI(kTag,
                 "pending consult deferred: identity/greeting in flight");
        return false;
    }

    const uint32_t generation =
        PresenceContext::GetInstance().PresenceGeneration();
    size_t count = 0;
    bool changed = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        for (auto& instance : instances_) {
            if (!IsActive(instance) || !SourceExists(instance) ||
                instance.source_type == ReminderSourceType::kInformation ||
                instance.status == ReminderStatus::kSnoozed ||
                instance.status == ReminderStatus::kAttentionSilenced ||
                instance.status == ReminderStatus::kAwaitingUndo ||
                instance.status == ReminderStatus::kPresenting ||
                instance.due_at > now) {
                continue;
            }
            if (!IsNormalTodo(instance) && !instance.missed) continue;
            ++count;
            if (instance.prompted_presence_generation != generation) {
                instance.prompted_presence_generation = generation;
                instance.updated_at = now;
                changed = true;
            }
        }
        if (count == 0 || !changed) return false;
        SaveLocked();
        if (store_dirty_) return false;
    }

    (void)long_return;
    // Cloud [PROACTIVE_RETURN] requires away_seconds >= 900. Short-absence
    // pending consult stays on local reminder cards / MCP, not RETURN.
    if (away_seconds < 900) {
        ESP_LOGI(kTag,
                 "pending consult skipped RETURN: away_seconds=%lld < 900",
                 static_cast<long long>(away_seconds));
        return true;
    }

    std::string face_identity = present_name.empty() ? "unknown" : present_name;
    for (char& ch : face_identity) {
        if (ch == '\n' || ch == '\r') ch = ' ';
    }
    if (face_identity.size() > 64) {
        face_identity.resize(64);
    }
    const size_t pending_clamped = count > 10000 ? 10000 : count;
    std::string event = "[PROACTIVE_RETURN]\n";
    event += "event=stable_user_return\n";
    event += "away_seconds=" + std::to_string(away_seconds) + "\n";
    event += "face_identity=" + face_identity + "\n";
    event += "pending_reminder_count=" + std::to_string(pending_clamped) + "\n";
    Application::GetInstance().StartChatWithText(event);
    return true;
}

size_t ReminderCoordinator::PendingBroadcastCount(time_t now) const {
    const_cast<ReminderCoordinator*>(this)->Initialize();
    std::lock_guard<std::mutex> lock(mutex_);
    size_t count = 0;
    for (const auto& instance : instances_) {
        if (!IsActive(instance) || !SourceExists(instance) ||
            instance.source_type == ReminderSourceType::kInformation ||
            instance.status == ReminderStatus::kSnoozed ||
            instance.status == ReminderStatus::kAttentionSilenced ||
            instance.status == ReminderStatus::kAwaitingUndo ||
            instance.status == ReminderStatus::kPresenting ||
            instance.due_at > now) {
            continue;
        }
        if (IsNormalTodo(instance) || instance.missed) ++count;
    }
    return count;
}

void ReminderCoordinator::MarkPendingBroadcastPrompted(time_t now) {
    Initialize();
    const uint32_t generation =
        PresenceContext::GetInstance().PresenceGeneration();
    std::lock_guard<std::mutex> lock(mutex_);
    bool changed = false;
    for (auto& instance : instances_) {
        if (!IsActive(instance) || !SourceExists(instance) ||
            instance.source_type == ReminderSourceType::kInformation ||
            instance.status == ReminderStatus::kSnoozed ||
            instance.status == ReminderStatus::kAttentionSilenced ||
            instance.status == ReminderStatus::kAwaitingUndo ||
            instance.status == ReminderStatus::kPresenting ||
            instance.due_at > now ||
            (!IsNormalTodo(instance) && !instance.missed)) {
            continue;
        }
        if (instance.prompted_presence_generation != generation) {
            instance.prompted_presence_generation = generation;
            instance.updated_at = now;
            changed = true;
        }
    }
    if (changed) SaveLocked();
}

bool ReminderCoordinator::BeginPendingBroadcast(time_t now) {
    Initialize();
    if (now == 0) now = time(nullptr);
    if (!PresenceContext::GetInstance().IsRadarPresent()) return false;
    broadcast_presence_generation_ =
        PresenceContext::GetInstance().PresenceGeneration();
    PresentNext(now, Application::GetInstance().GetDeviceState() ==
                         kDeviceStateIdle);
    return true;
}

bool ReminderCoordinator::SkipCurrentBroadcast() {
    Initialize();
    std::string dismiss_id;
    uint32_t dismiss_revision = 0;
    const uint32_t generation =
        PresenceContext::GetInstance().PresenceGeneration();
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (current_instance_id_.empty()) return false;
        ReminderInstance* current = FindLocked(current_instance_id_);
        if (!current || !IsNormalTodo(*current) ||
            current->status != ReminderStatus::kPresenting) {
            return false;
        }
        dismiss_id = current->instance_id;
        dismiss_revision = current->revision;
        current->deferred_presence_generation = generation;
        current->status = ReminderStatus::kQueued;
        current->card_expires_at = 0;
        current->updated_at = time(nullptr);
        AdvanceRevisionLocked(*current);
        current_instance_id_.clear();
        SaveLocked();
    }
    DismissVisual(dismiss_id, dismiss_revision, "next_item");
    PresentNext(time(nullptr), Application::GetInstance().GetDeviceState() ==
                                  kDeviceStateIdle);
    return true;
}

void ReminderCoordinator::StopPendingBroadcast() {
    Initialize();
    std::string dismiss_id;
    uint32_t dismiss_revision = 0;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        // Stopping is deliberately different from "next": it ends this
        // broadcast round and preserves every unhandled item for a later
        // presence generation instead of advancing to another card.
        broadcast_presence_generation_ = 0;
        ReminderInstance* current = current_instance_id_.empty()
            ? nullptr : FindLocked(current_instance_id_);
        if (current && IsNormalTodo(*current) &&
            current->status == ReminderStatus::kPresenting) {
            dismiss_id = current->instance_id;
            dismiss_revision = current->revision;
            current->deferred_presence_generation =
                PresenceContext::GetInstance().PresenceGeneration();
            current->status = ReminderStatus::kQueued;
            current->card_expires_at = 0;
            current->updated_at = time(nullptr);
            AdvanceRevisionLocked(*current);
            current_instance_id_.clear();
        }
        SaveLocked();
    }
    if (!dismiss_id.empty()) {
        ReminderControlClient::GetInstance().Cancel("user_action");
        DismissVisual(dismiss_id, dismiss_revision, "stop_broadcast");
    }
}

void ReminderCoordinator::RenewCurrentCardWindow(time_t now) {
    Initialize();
    if (now == 0) now = time(nullptr);
    ReminderInstance copy;
    bool renew = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        ReminderInstance* current = current_instance_id_.empty()
            ? nullptr : FindLocked(current_instance_id_);
        if (current && current->status == ReminderStatus::kPresenting) {
            current->card_expires_at = now + kCardInteractionWindowSeconds;
            copy = *current;
            renew = true;
        }
    }
    if (renew) {
        Application::GetInstance().BeginReminderInteraction(
            copy.instance_id, copy.revision, copy.card_expires_at);
    }
}

bool ReminderCoordinator::RequiresPersonalDelivery(
    const ReminderInstance& instance) const {
    (void)instance;
    return false;
}

bool ReminderCoordinator::RequiresPresenceForDelivery(
    const ReminderInstance& instance) const {
    return instance.source_type == ReminderSourceType::kNote ||
           instance.source_type == ReminderSourceType::kHabit;
}

bool ReminderCoordinator::IsAllUsersRecipient(
    const ReminderInstance& instance) {
    return instance.recipient_person_id.empty() ||
           instance.recipient_person_id == "all";
}

bool ReminderCoordinator::IsNormalTodo(const ReminderInstance& instance) {
    return instance.source_type == ReminderSourceType::kNote ||
           instance.source_type == ReminderSourceType::kHabit;
}

bool ReminderCoordinator::AllowNoFaceOwnerBypassLocked(
    const ReminderInstance& instance) const {
    if (!RequiresPersonalDelivery(instance)) return false;
    // Legacy bypass retained only to migrate existing reminder records.
    // Unknown / known_one_or_more / missing default_owner → no bypass.
    return FaceRoster::GetInstance().AllowsNoFaceOwnerBypass(
        instance.recipient_person_id);
}

void ReminderCoordinator::ApplyRecipientFields(
    ReminderInstance& instance, const std::string& owner,
    const std::string& recipient_person_id,
    const std::string& creator_person_id,
    const std::string& recipient_display_name) {
    // owner_user_id is management ownership (= creator). Never overwrite with
    // recipient — otherwise "mom reminds son" makes mom unable to manage.
    instance.owner_user_id = owner.empty() ? "default" : owner;
    instance.creator_person_id = creator_person_id;
    if (instance.creator_person_id.empty() &&
        PresenceContext::IsStableUserId(instance.owner_user_id)) {
        instance.creator_person_id = instance.owner_user_id;
    }
    if (!instance.creator_person_id.empty()) {
        instance.owner_user_id = instance.creator_person_id;
    }
    if (!recipient_person_id.empty()) {
        instance.recipient_person_id = recipient_person_id;
    } else {
        const std::string speaker =
            UserContext::GetInstance().GetCurrentSpeakerUserId();
        instance.recipient_person_id =
            PresenceContext::IsStableUserId(speaker) ? speaker : "all";
    }
    instance.recipient_display_name_snapshot = recipient_display_name;
    instance.delivery_unbound = false;
}

void ReminderCoordinator::MigrateRecipientLocked(ReminderInstance& instance) {
    if (instance.recipient_person_id.empty()) {
        instance.recipient_person_id = "all";
    }
    instance.delivery_unbound = false;
}

int ReminderCoordinator::Rank(const ReminderInstance& instance,
                              time_t now) const {
    if (instance.priority == ReminderPriority::kHigh &&
        instance.due_at <= now) return 0;
    if (instance.priority == ReminderPriority::kHigh &&
        instance.pre_alert_at > 0 && instance.pre_alert_at <= now) return 1;
    if (instance.priority == ReminderPriority::kNormal &&
        instance.due_at <= now) return 2;
    if (instance.status == ReminderStatus::kSnoozed &&
        instance.next_attention_at <= now) return 3;
    return 4;
}

bool ReminderCoordinator::EnqueueAlarm(
    int source_id, const std::string& owner, const std::string& title,
    time_t due_at, const std::string& occurrence_key,
    const std::string& recipient_person_id,
    const std::string& creator_person_id) {
    ReminderInstance instance;
    instance.source_type = ReminderSourceType::kAlarm;
    instance.source_id = source_id;
    instance.instance_id =
        "alarm:" + std::to_string(source_id) + ":" + occurrence_key;
    ApplyRecipientFields(instance, owner, recipient_person_id,
                         creator_person_id, "");
    instance.priority = ReminderPriority::kHigh;
    instance.due_at = due_at;
    instance.occurrence_key = occurrence_key;
    instance.title = title.empty() ? "闹钟" : title;
    instance.detail = "闹钟已到时间";
    instance.action_policy = PolicyFor(instance.source_type);
    return Enqueue(std::move(instance));
}

bool ReminderCoordinator::EnqueueNote(
    int source_id, const std::string& owner, const std::string& title,
    time_t due_at, const std::string& occurrence_key,
    const std::string& priority, const std::string& attention_policy,
    int pre_alert_minutes, const std::string& recipient_person_id,
    const std::string& creator_person_id,
    const std::string& recipient_display_name) {
    ReminderInstance instance;
    instance.source_type = ReminderSourceType::kNote;
    instance.source_id = source_id;
    instance.instance_id =
        "note:" + std::to_string(source_id) + ":" + occurrence_key;
    ApplyRecipientFields(instance, owner, recipient_person_id,
                         creator_person_id, recipient_display_name);
    instance.priority = priority == "high"
        ? ReminderPriority::kHigh : ReminderPriority::kNormal;
    instance.attention_policy = attention_policy;
    instance.due_at = due_at;
    if (instance.priority == ReminderPriority::kHigh &&
        attention_policy == "pickup" && pre_alert_minutes > 0) {
        instance.pre_alert_at = due_at - pre_alert_minutes * 60;
    }
    instance.occurrence_key = occurrence_key;
    instance.title = title;
    instance.detail = "一次性提醒";
    instance.action_policy = PolicyFor(instance.source_type);
    return Enqueue(std::move(instance));
}

bool ReminderCoordinator::EnqueueHabit(
    int source_id, const std::string& owner, const std::string& title,
    time_t due_at, const std::string& occurrence_key,
    const std::string& recipient_person_id,
    const std::string& creator_person_id) {
    ReminderInstance instance;
    instance.source_type = ReminderSourceType::kHabit;
    instance.source_id = source_id;
    instance.instance_id =
        "habit:" + std::to_string(source_id) + ":" + occurrence_key;
    ApplyRecipientFields(instance, owner, recipient_person_id,
                         creator_person_id, "");
    instance.priority = ReminderPriority::kNormal;
    instance.due_at = due_at;
    instance.occurrence_key = occurrence_key;
    instance.title = title;
    instance.detail = "今日习惯";
    instance.action_policy = PolicyFor(instance.source_type);
    return Enqueue(std::move(instance));
}

bool ReminderCoordinator::EnqueueInformation(
    const std::string& title, const std::vector<std::string>& details,
    uint32_t auto_dismiss_ms) {
    (void)auto_dismiss_ms;
    ReminderInstance instance;
    instance.source_type = ReminderSourceType::kInformation;
    instance.priority = ReminderPriority::kLow;
    instance.owner_user_id = "default";
    instance.due_at = time(nullptr);
    instance.occurrence_key = std::to_string(instance.due_at) + "-" +
                              std::to_string(++information_sequence_);
    instance.instance_id = "information:0:" + instance.occurrence_key;
    instance.title = title.empty() ? "信息" : title;
    for (const auto& detail : details) {
        if (!instance.detail.empty()) instance.detail += '\n';
        instance.detail += detail;
    }
    instance.next_attention_at =
        instance.due_at + kCardInteractionWindowSeconds;
    instance.action_policy = PolicyFor(instance.source_type);
    return Enqueue(std::move(instance));
}

bool ReminderCoordinator::Enqueue(ReminderInstance instance) {
    Initialize();
    const time_t now = time(nullptr);
    ReminderInstance request_instance;
    bool should_request = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        auto duplicate = std::find_if(
            instances_.begin(), instances_.end(),
            [&](const ReminderInstance& item) {
                return item.instance_id == instance.instance_id;
            });
        const auto before_instances = instances_;
        if (duplicate != instances_.end()) {
            const bool semantics_changed =
                duplicate->title != instance.title ||
                duplicate->detail != instance.detail ||
                duplicate->priority != instance.priority ||
                duplicate->attention_policy !=
                    instance.attention_policy ||
                duplicate->due_at != instance.due_at ||
                duplicate->pre_alert_at != instance.pre_alert_at;
            if (!semantics_changed) return true;
            duplicate->title = instance.title;
            duplicate->detail = instance.detail;
            duplicate->priority = instance.priority;
            duplicate->attention_policy =
                instance.attention_policy;
            duplicate->due_at = instance.due_at;
            duplicate->pre_alert_at = instance.pre_alert_at;
            duplicate->updated_at = now;
            AdvanceVoiceRevisionLocked(*duplicate);
            AdvanceRevisionLocked(*duplicate);
            duplicate->voice_request_revision =
                duplicate->voice_revision;
            duplicate->voice_request_at = now;
            request_instance = *duplicate;
            should_request =
                duplicate->source_type !=
                ReminderSourceType::kInformation;
            SaveLocked();
            if (store_dirty_) {
                instances_ = before_instances;
                SaveLocked();
                return false;
            }
        } else {

            instance.status = ReminderStatus::kQueued;
            instance.revision = 1;
            instance.voice_revision = 1;
            if (instance.source_type !=
                ReminderSourceType::kInformation) {
                instance.voice_request_revision =
                    instance.voice_revision;
                instance.voice_request_at = now;
            }
            instance.created_at = now;
            instance.updated_at = now;
            if (instance.due_at == 0) instance.due_at = now;
            while (instances_.size() >= kMaxInstances) {
                auto removable = std::find_if(
                    instances_.begin(), instances_.end(),
                    [&](const ReminderInstance& item) {
                        return !IsActive(item);
                    });
                if (removable == instances_.end()) {
                    ESP_LOGE(kTag,
                             "Reminder instance capacity exhausted");
                    return false;
                }
                InvalidateVoiceAssetsLocked(*removable);
                instances_.erase(removable);
            }
            instances_.push_back(instance);
            request_instance = instance;
            should_request =
                instance.source_type !=
                ReminderSourceType::kInformation;
            SaveLocked();
            if (store_dirty_) {
                instances_ = before_instances;
                SaveLocked();
                return false;
            }
        }
    }
    // Personal AI voice is requested only after recipient identity confirmation.
    if (should_request &&
        !RequiresPersonalDelivery(request_instance)) {
        ReminderVoiceService::GetInstance().RequestScripts(
            request_instance);
    }
    return true;
}

ReminderInstance* ReminderCoordinator::FindLocked(
    const std::string& instance_id) {
    for (auto& instance : instances_) {
        if (instance.instance_id == instance_id) return &instance;
    }
    return nullptr;
}

ReminderInstance* ReminderCoordinator::FindActiveBySourceLocked(
    ReminderSourceType type, int source_id) {
    for (auto it = instances_.rbegin(); it != instances_.rend(); ++it) {
        if (it->source_type == type && it->source_id == source_id &&
            IsActive(*it)) {
            return &*it;
        }
    }
    return nullptr;
}

void ReminderCoordinator::FinalizeUndoLocked(ReminderInstance& instance,
                                              time_t now) {
    if (instance.status != ReminderStatus::kAwaitingUndo ||
        instance.undo_deadline == 0 || now < instance.undo_deadline) {
        return;
    }
    instance.status = instance.pending_final_action == "skipped"
        ? ReminderStatus::kSkipped : ReminderStatus::kCompleted;
    instance.last_action = instance.pending_final_action;
    instance.pending_final_action.clear();
    instance.undo_deadline = 0;
    instance.updated_at = now;
    AdvanceRevisionLocked(instance);
}

void ReminderCoordinator::Tick(time_t now, bool device_idle) {
    // Sync and retire old identities before a new connection can present an
    // instance loaded from disk. Offline state cannot invent a new identity.
    if (!PersonDirectory::GetInstance().Ready()) return;
    Initialize();
    bool dismiss_visual = false;
    const char* dismiss_reason = "timeout";
    std::string dismiss_instance_id;
    uint32_t dismiss_revision = 0;
    std::vector<ReminderInstance> repeat_attention;
    std::vector<ReminderInstance> unattended_chimes;
    std::vector<ReminderInstance> finalized_instances;
    std::vector<ReminderInstance> deferred_voice;
    size_t active_pending_count = 0;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        bool changed = false;
        for (auto& instance : instances_) {
            const ReminderStatus before = instance.status;
            const uint32_t revision_before = instance.revision;
            if (InvalidateMissingSourceLocked(instance, now,
                                              &dismiss_instance_id,
                                              &dismiss_revision)) {
                if (!dismiss_instance_id.empty()) {
                    dismiss_visual = true;
                    dismiss_reason = "resolved";
                }
                changed = true;
                continue;
            }
            if (IsActive(instance)) active_pending_count++;
            FinalizeUndoLocked(instance, now);
            if (before == ReminderStatus::kAwaitingUndo &&
                instance.status != ReminderStatus::kAwaitingUndo &&
                current_instance_id_ == instance.instance_id) {
                dismiss_instance_id = instance.instance_id;
                dismiss_revision = revision_before;
                current_instance_id_.clear();
                dismiss_visual = true;
            }
            if (before == ReminderStatus::kAwaitingUndo &&
                instance.status != ReminderStatus::kAwaitingUndo) {
                finalized_instances.push_back(instance);
            }
            if (instance.status == ReminderStatus::kSnoozed &&
                instance.next_attention_at <= now) {
                instance.status = ReminderStatus::kQueued;
                instance.updated_at = now;
                AdvanceRevisionLocked(instance);
            } else if (instance.status == ReminderStatus::kAttentionSilenced &&
                       instance.attention_silenced_until <= now) {
                instance.status = ReminderStatus::kQueued;
                instance.updated_at = now;
                AdvanceRevisionLocked(instance);
            }

            // A normal to-do is never presented into an empty room.  It gets
            // exactly one local attention chime and remains durable until a
            // later stable presence can be asked for consent to read it.
            if (IsNormalTodo(instance) && IsActive(instance) &&
                instance.due_at <= now &&
                !PresenceContext::GetInstance().IsRadarPresent() &&
                !instance.unattended_chime_emitted) {
                instance.unattended_chime_emitted = true;
                instance.status = ReminderStatus::kWaitingPresence;
                instance.next_attention_at = 0;
                instance.updated_at = now;
                AdvanceRevisionLocked(instance);
                unattended_chimes.push_back(instance);
                changed = true;
            }

            if (device_idle && instance.status == ReminderStatus::kPresenting &&
                instance.voice_deferred && !instance.missed) {
                instance.voice_deferred = false;
                instance.updated_at = now;
                deferred_voice.push_back(instance);
                changed = true;
            }

            if (instance.status == ReminderStatus::kPresenting) {
                if (instance.source_type == ReminderSourceType::kAlarm &&
                    instance.alarm_attention_started_at > 0 &&
                    now >= instance.alarm_attention_started_at +
                               kAlarmAttentionWindowSeconds) {
                    // Stop this occurrence after an hour.  Keep a durable
                    // missed marker; it is surfaced when somebody returns,
                    // while the next recurring occurrence remains independent.
                    instance.missed = true;
                    instance.status = ReminderStatus::kWaitingPresence;
                    instance.next_attention_at = 0;
                    instance.card_expires_at = 0;
                    instance.updated_at = now;
                    if (current_instance_id_ == instance.instance_id) {
                        dismiss_instance_id = instance.instance_id;
                        dismiss_revision = instance.revision;
                        current_instance_id_.clear();
                        dismiss_visual = true;
                    }
                    AdvanceRevisionLocked(instance);
                    ESP_LOGI(kTag,
                             "[REMINDER_DELIVERY] event=alarm_missed instance=%s",
                             instance.instance_id.c_str());
                } else if (instance.source_type != ReminderSourceType::kInformation &&
                           instance.card_expires_at > 0 &&
                           now >= instance.card_expires_at) {
                    // No touch/voice action within 180 seconds: hide the
                    // card but retain the pending item until the next stable
                    // presence event.  Alarms continue their 3-minute cycle.
                    instance.card_expires_at = 0;
                    instance.status = instance.source_type ==
                            ReminderSourceType::kAlarm && !instance.missed
                        ? ReminderStatus::kQueued
                        : ReminderStatus::kWaitingPresence;
                    instance.updated_at = now;
                    if (current_instance_id_ == instance.instance_id) {
                        dismiss_instance_id = instance.instance_id;
                        dismiss_revision = instance.revision;
                        current_instance_id_.clear();
                        dismiss_visual = true;
                    }
                    AdvanceRevisionLocked(instance);
                } else if (instance.priority == ReminderPriority::kHigh &&
                    instance.source_type != ReminderSourceType::kAlarm &&
                    instance.last_presented_at < instance.due_at &&
                    now >= instance.due_at) {
                    instance.status = ReminderStatus::kQueued;
                    instance.next_attention_at = now;
                    instance.updated_at = now;
                    if (current_instance_id_ == instance.instance_id) {
                        dismiss_instance_id = instance.instance_id;
                        dismiss_revision = instance.revision;
                        current_instance_id_.clear();
                        dismiss_visual = true;
                    }
                    AdvanceRevisionLocked(instance);
                } else if (instance.source_type == ReminderSourceType::kInformation &&
                    instance.next_attention_at > 0 &&
                    instance.next_attention_at <= now) {
                    instance.status = ReminderStatus::kExpired;
                    instance.updated_at = now;
                    if (current_instance_id_ == instance.instance_id) {
                        dismiss_instance_id = instance.instance_id;
                        dismiss_revision = instance.revision;
                        current_instance_id_.clear();
                        dismiss_visual = true;
                    }
                    AdvanceRevisionLocked(instance);
                } else if (instance.priority == ReminderPriority::kHigh &&
                           instance.last_presented_at < instance.due_at &&
                           now >= instance.due_at) {
                    // Handled above for high pre-alert transition.
                }
            }

            if (instance.source_type == ReminderSourceType::kAlarm &&
                IsActive(instance) &&
                !instance.missed &&
                instance.status != ReminderStatus::kSnoozed &&
                instance.status != ReminderStatus::kAttentionSilenced &&
                instance.next_attention_at > 0 &&
                instance.next_attention_at <= now) {
                instance.repeat_count++;
                instance.next_attention_at = now + kAlarmRepeatSeconds;
                instance.status = ReminderStatus::kPresenting;
                instance.card_expires_at = now + kCardInteractionWindowSeconds;
                current_instance_id_ = instance.instance_id;
                instance.updated_at = now;
                AdvanceRevisionLocked(instance);
                repeat_attention.push_back(instance);
            }
            changed = changed || before != instance.status ||
                      revision_before != instance.revision;
        }
        if (changed || !repeat_attention.empty() || store_dirty_) {
            SaveLocked();
        }
        if (store_dirty_) finalized_instances.clear();
    }
    if (dismiss_visual) {
        if (std::strcmp(dismiss_reason, "resolved") == 0) {
            ReminderControlClient::GetInstance().Cancel("source_missing");
        }
        DismissVisual(dismiss_instance_id, dismiss_revision, dismiss_reason);
    }
    for (const auto& instance : finalized_instances) {
        if (instance.source_type == ReminderSourceType::kNote) {
            NoteManager::GetInstance().CompleteOccurrence(instance.source_id);
        } else if (instance.source_type == ReminderSourceType::kHabit &&
                   instance.status == ReminderStatus::kCompleted) {
            HabitManager::GetInstance().Confirm(instance.source_id);
        } else if (instance.source_type == ReminderSourceType::kHabit &&
                   instance.status == ReminderStatus::kSkipped) {
            HabitManager::GetInstance().Reject(instance.source_id);
        }
    }
    for (const auto& instance : deferred_voice) {
        if (RequiresPresenceForDelivery(instance) &&
            !PresenceContext::GetInstance().IsRadarPresent()) {
            continue;
        }
        ESP_LOGI(kTag,
                 "[REMINDER_DELIVERY] event=deferred_voice_resume instance=%s",
                 instance.instance_id.c_str());
        AnnounceDueVoice(instance, std::max<size_t>(active_pending_count, 1),
                         false, true);
    }
    for (const auto& instance : unattended_chimes) {
        ESP_LOGI(kTag,
                 "[REMINDER_DELIVERY] event=unattended_chime instance=%s",
                 instance.instance_id.c_str());
        ReminderVoiceService::GetInstance().PlayAttention(instance, "due");
    }
    for (const auto& instance : repeat_attention) {
        if (instance.source_type != ReminderSourceType::kAlarm ||
            instance.missed) {
            continue;
        }
        ReminderVoiceService::GetInstance().PlayAttention(instance, "repeat");
        Present(instance, 1);
    }
    // High/alarm re-attention also must pass the personal delivery gate.
    // Single due to-do with someone nearby: present and play local ogg.
    // Two or more: LLM consult only; do not arm broadcast until the user
    // agrees via reminder.begin_broadcast.
    if (device_idle && PresenceContext::GetInstance().IsRadarPresent()) {
        const size_t pending = PendingBroadcastCount(now);
        if (pending >= 2) {
            RequestPendingBroadcastPrompt(now, false);
        } else if (pending == 1) {
            std::lock_guard<std::mutex> lock(mutex_);
            broadcast_presence_generation_ =
                PresenceContext::GetInstance().PresenceGeneration();
        }
    }
    PresentNext(now, device_idle);
}

bool ReminderCoordinator::TryBeginDeliveryLocked(
    ReminderInstance& instance, time_t now,
    uint32_t presence_generation, bool* request_verify) {
    if (request_verify) *request_verify = false;
    if (instance.delivery_unbound ||
        !PresenceContext::IsUsrPersonId(instance.recipient_person_id)) {
        instance.status = ReminderStatus::kWaitingRecipient;
        instance.updated_at = now;
        ESP_LOGW(kTag,
                 "[REMINDER_DELIVERY] event=due instance=%s source=%s "
                 "recipient=- reason=unbound",
                 instance.instance_id.c_str(),
                 SourceTypeName(instance.source_type));
        test_observability::Event("reminder", "delivery_gate",
                                  presence_generation, "blocked",
                                  "recipient_unbound");
        return false;
    }
    auto& presence = PresenceContext::GetInstance();
    // No-face bypass still requires stable radar presence.
    if (!presence.IsRadarPresent()) {
        instance.status = ReminderStatus::kWaitingPresence;
        instance.updated_at = now;
        ESP_LOGI(kTag,
                 "[REMINDER_DELIVERY] event=wait_presence instance=%s "
                 "recipient=%s",
                 instance.instance_id.c_str(),
                 instance.recipient_person_id.c_str());
        test_observability::Event("reminder", "delivery_gate",
                                  presence_generation, "blocked", "radar_absent");
        return false;
    }
    // No face templates on this account/device: default-owner reminders created
    // locally may present and be acted on without face confirmation.
    if (AllowNoFaceOwnerBypassLocked(instance)) {
        instance.no_face_owner_bypass = true;
        instance.last_verified_person_id = instance.recipient_person_id;
        ESP_LOGI(kTag,
                 "[REMINDER_DELIVERY] event=no_face_owner_bypass instance=%s "
                 "recipient=%s",
                 instance.instance_id.c_str(),
                 instance.recipient_person_id.c_str());
        test_observability::Event("reminder", "delivery_gate",
                                  presence_generation, "allowed", "no_face_owner");
        return true;
    }
    instance.no_face_owner_bypass = false;
    if (instance.next_identity_retry_at > now) {
        instance.status = ReminderStatus::kWaitingRecipient;
        instance.updated_at = now;
        test_observability::Event("reminder", "delivery_gate",
                                  presence_generation, "blocked", "identity_backoff");
        return false;
    }
    if (presence.ConfirmedMatches(instance.recipient_person_id,
                                  presence_generation)) {
        test_observability::Event("reminder", "delivery_gate",
                                  presence_generation, "allowed", "face_confirmed");
        return true;
    }
    if (!IdentityClient::GetInstance().HasIdentityEndpoint()) {
        instance.status = ReminderStatus::kWaitingRecipient;
        instance.next_identity_retry_at = now + kIdentityRetrySeconds;
        instance.updated_at = now;
        ESP_LOGW(kTag,
                 "[REMINDER_DELIVERY] event=retry_scheduled instance=%s "
                 "reason=vision_not_ready next_in=%ld",
                 instance.instance_id.c_str(),
                 static_cast<long>(kIdentityRetrySeconds));
        test_observability::Event("reminder", "delivery_gate",
                                  presence_generation, "blocked",
                                  "identity_endpoint_missing");
        return false;
    }
    instance.status = ReminderStatus::kVerifyingIdentity;
    instance.delivery_presence_generation = presence_generation;
    instance.last_delivery_attempt_at = now;
    instance.updated_at = now;
    if (request_verify) *request_verify = true;
    test_observability::Event("reminder", "delivery_gate", presence_generation,
                              "pending", "face_verification");
    return false;
}

void ReminderCoordinator::RequestIdentityVerification(
    const ReminderInstance& instance) {
    ReminderIdentityRequest request;
    request.instance_id = instance.instance_id;
    request.revision = instance.revision;
    request.recipient_person_id = instance.recipient_person_id;
    request.presence_generation = instance.delivery_presence_generation;
    const bool accepted =
        ReminderIdentityVerifier::GetInstance().RequestVerification(
            request,
            [this](const ReminderIdentityOutcome& outcome) {
                Application::GetInstance().Schedule([this, outcome]() {
                    OnIdentityVerificationResult(
                        outcome.request.instance_id,
                        outcome.request.revision,
                        outcome.request.presence_generation,
                        outcome.confirmed, outcome.reason,
                        outcome.second.IsKnownPerson()
                            ? outcome.second.user_id
                            : outcome.first.user_id,
                        outcome.second.display_name.empty()
                            ? outcome.first.display_name
                            : outcome.second.display_name);
                });
            });
    if (!accepted) {
        std::lock_guard<std::mutex> lock(mutex_);
        ReminderInstance* live = FindLocked(instance.instance_id);
        if (!live) return;
        live->status = ReminderStatus::kWaitingRecipient;
        live->next_identity_retry_at =
            time(nullptr) + kIdentityRetrySeconds;
        live->updated_at = time(nullptr);
        SaveLocked();
        ESP_LOGI(kTag,
                 "[REMINDER_DELIVERY] event=retry_scheduled instance=%s "
                 "reason=camera_busy",
                 instance.instance_id.c_str());
    }
}

void ReminderCoordinator::OnPresenceChanged(bool present) {
    // Prefer ApplyStablePresence/Absence from ProactiveWakeCoordinator.
    // Keep SetRadarPresent only when context is out of sync (legacy callers).
    if (PresenceContext::GetInstance().IsRadarPresent() != present) {
        PresenceContext::GetInstance().SetRadarPresent(present);
    }
    const time_t now = time(nullptr);
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (present) {
            for (auto& instance : instances_) {
                if (instance.status == ReminderStatus::kWaitingPresence &&
                    instance.card_expires_at == 0) {
                    instance.status = ReminderStatus::kQueued;
                    instance.next_attention_at = now;
                    instance.updated_at = now;
                    AdvanceRevisionLocked(instance);
                }
            }
            SaveLocked();
        }
    }
    if (present) {
        Application::GetInstance().RefreshReminderInteraction();
    }
    test_observability::Event("reminder", "presence_gate",
                              PresenceContext::GetInstance().PresenceGeneration(),
                              present ? "present" : "absent",
                              present ? "resume_pending" : "delivery_paused", 0);
}

void ReminderCoordinator::HidePersonalCardForAbsenceLocked(
    time_t now, std::string* dismiss_id, uint32_t* dismiss_rev) {
    if (current_instance_id_.empty()) return;
    ReminderInstance* current = FindLocked(current_instance_id_);
    if (!current || current->status != ReminderStatus::kPresenting) return;
    if (!RequiresPersonalDelivery(*current)) return;
    if (dismiss_id) *dismiss_id = current->instance_id;
    if (dismiss_rev) *dismiss_rev = current->revision;
    current->status = ReminderStatus::kWaitingPresence;
    current->updated_at = now;
    AdvanceRevisionLocked(*current);
    current_instance_id_.clear();
    ESP_LOGI(kTag,
             "[REMINDER_DELIVERY] event=card_hide instance=%s rev=%u "
             "reason=absence",
             current->instance_id.c_str(),
             static_cast<unsigned>(current->revision));
}

void ReminderCoordinator::OnIdentityVerificationResult(
    const std::string& instance_id, uint32_t revision,
    uint32_t presence_generation, bool confirmed, const std::string& reason,
    const std::string& verified_person_id,
    const std::string& verified_display_name) {
    const time_t now = time(nullptr);
    ReminderInstance selected;
    bool present_now = false;
    bool preempt = false;
    std::string preempted_instance_id;
    uint32_t preempted_revision = 0;
    size_t pending_count = 0;
    bool request_voice = false;
    bool play_chime = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        ReminderInstance* instance = FindLocked(instance_id);
        if (!instance || instance->revision != revision ||
            !IsActive(*instance)) {
            ESP_LOGI(kTag,
                     "[REMINDER_DELIVERY] event=verify_rejected "
                     "instance=%s reason=stale",
                     instance_id.c_str());
            return;
        }
        auto& presence = PresenceContext::GetInstance();
        if (!presence.IsRadarPresent() ||
            presence.PresenceGeneration() != presence_generation ||
            instance->delivery_presence_generation != presence_generation) {
            instance->status = ReminderStatus::kWaitingPresence;
            instance->updated_at = now;
            SaveLocked();
            ESP_LOGI(kTag,
                     "[REMINDER_DELIVERY] event=verify_rejected "
                     "instance=%s reason=stale_generation",
                     instance_id.c_str());
            return;
        }
        if (!confirmed ||
            verified_person_id != instance->recipient_person_id) {
            instance->status = ReminderStatus::kWaitingRecipient;
            instance->next_identity_retry_at = now + kIdentityRetrySeconds;
            instance->updated_at = now;
            SaveLocked();
            ESP_LOGI(kTag,
                     "[REMINDER_DELIVERY] event=verify_rejected "
                     "instance=%s reason=%s",
                     instance_id.c_str(),
                     reason.empty() ? "rejected" : reason.c_str());
            return;
        }
        ESP_LOGI(kTag,
                 "[REMINDER_DELIVERY] event=verify_confirmed instance=%s "
                 "recipient=%s gen=%u",
                 instance_id.c_str(), verified_person_id.c_str(),
                 static_cast<unsigned>(presence_generation));
        instance->last_verified_person_id = verified_person_id;
        if (!verified_display_name.empty()) {
            instance->recipient_display_name_snapshot = verified_display_name;
        }
        UserContext::GetInstance().SetActiveUserId(verified_person_id);

        ReminderInstance* current = current_instance_id_.empty()
            ? nullptr : FindLocked(current_instance_id_);
        const ReminderInstance instance_before = *instance;
        const std::string current_before = current_instance_id_;
        ReminderInstance current_before_value;
        const bool had_current =
            current && current->instance_id != instance->instance_id;
        if (had_current) current_before_value = *current;

        if (current && current->status == ReminderStatus::kPresenting &&
            current->instance_id != instance->instance_id) {
            if (Rank(*instance, now) >= Rank(*current, now)) {
                instance->status = ReminderStatus::kWaitingRecipient;
                instance->next_identity_retry_at = now + 5;
                instance->updated_at = now;
                SaveLocked();
                ESP_LOGI(kTag,
                         "[REMINDER_DELIVERY] event=preempt_deferred "
                         "instance=%s keeping=%s",
                         instance->instance_id.c_str(),
                         current->instance_id.c_str());
                return;
            }
            preempted_instance_id = current->instance_id;
            preempted_revision = current->revision;
            if (RequiresPersonalDelivery(*current)) {
                current->status = ReminderStatus::kWaitingRecipient;
                current->next_identity_retry_at = now + 5;
            } else {
                current->status = ReminderStatus::kQueued;
                current->next_attention_at = now;
            }
            current->updated_at = now;
            AdvanceRevisionLocked(*current);
            preempt = true;
            ESP_LOGI(kTag,
                     "[REMINDER_DELIVERY] event=preempt_old "
                     "old=%s old_rev=%u new=%s",
                     preempted_instance_id.c_str(),
                     static_cast<unsigned>(preempted_revision),
                     instance->instance_id.c_str());
        }

        instance->status = ReminderStatus::kPresenting;
        instance->last_presented_at = now;
        instance->card_expires_at = now + kCardInteractionWindowSeconds;
        instance->voice_deferred =
            Application::GetInstance().GetDeviceState() != kDeviceStateIdle;
        instance->updated_at = now;
        instance->delivery_presence_generation = presence_generation;
        instance->bound_session_id =
            Application::GetInstance().GetAudioSessionId();
        AdvanceRevisionLocked(*instance);
        if (instance->source_type == ReminderSourceType::kAlarm &&
            instance->next_attention_at == 0) {
            instance->next_attention_at = now + kAlarmRepeatSeconds;
        } else {
            // Ordinary to-dos never use a 5/10-minute repeat strategy.
            instance->next_attention_at = 0;
        }
        play_chime = !instance->voice_deferred &&
            instance->chime_presence_generation != presence_generation;
        if (play_chime) {
            instance->chime_presence_generation = presence_generation;
        }
        request_voice = !instance->voice_deferred &&
            instance->voice_presence_generation != presence_generation &&
            (instance->voice_request_revision != instance->voice_revision ||
             instance->voice_request_at == 0 ||
             now - instance->voice_request_at >= 60);
        if (request_voice) {
            instance->voice_request_revision = instance->voice_revision;
            instance->voice_request_at = now;
            instance->voice_presence_generation = presence_generation;
        }
        current_instance_id_ = instance->instance_id;
        for (const auto& item : instances_) {
            if (IsActive(item)) pending_count++;
        }
        selected = *instance;
        SaveLocked();
        if (store_dirty_) {
            *instance = instance_before;
            if (had_current) {
                ReminderInstance* restored =
                    FindLocked(current_before_value.instance_id);
                if (restored) *restored = current_before_value;
            }
            current_instance_id_ = current_before;
            ESP_LOGW(kTag,
                     "[REMINDER_DELIVERY] event=present_rollback "
                     "instance=%s reason=save_failed",
                     instance_id.c_str());
            return;
        }
        present_now = true;
    }
    if (!present_now) return;
    test_observability::Event("reminder", "present",
                              presence_generation, "requested",
                              SourceTypeName(selected.source_type),
                              selected.repeat_count);
    if (preempt) {
        ReminderControlClient::GetInstance().Cancel("preempted");
        DismissVisual(preempted_instance_id, preempted_revision, "preempted");
    }
    if (selected.source_type == ReminderSourceType::kAlarm &&
        Application::GetInstance().GetDeviceState() == kDeviceStateSpeaking) {
        // Alarm is the single reminder type permitted to interrupt ordinary
        // dialogue.  AbortSpeaking also flushes old local PCM/subtitles.
        Application::GetInstance().AbortSpeaking(kAbortReasonNone);
    }
    if (play_chime || request_voice) {
        AnnounceDueVoice(selected, pending_count, false, play_chime);
    }
    ESP_LOGI(kTag,
             "[REMINDER_DELIVERY] event=card_show instance=%s rev=%u "
             "title_len=%u",
             selected.instance_id.c_str(),
             static_cast<unsigned>(selected.revision),
             static_cast<unsigned>(selected.title.size()));
    Present(selected, pending_count);
}

void ReminderCoordinator::PresentNext(time_t now, bool device_idle) {
    ReminderInstance selected;
    ReminderInstance verify_target;
    bool have_selected = false;
    bool request_verify = false;
    bool preempt = false;
    std::string preempted_instance_id;
    uint32_t preempted_revision = 0;
    bool request_voice = false;
    bool play_chime = false;
    size_t pending_count = 0;
    const uint32_t presence_generation =
        PresenceContext::GetInstance().PresenceGeneration();
    {
        std::lock_guard<std::mutex> lock(mutex_);
        ReminderInstance* current = current_instance_id_.empty()
            ? nullptr : FindLocked(current_instance_id_);
        ReminderInstance* best = nullptr;
        for (auto& instance : instances_) {
            if (IsActive(instance) && SourceExists(instance)) pending_count++;
            const bool due_or_pre_alert =
                instance.due_at <= now ||
                (instance.priority == ReminderPriority::kHigh &&
                 instance.pre_alert_at > 0 &&
                 instance.pre_alert_at <= now);
            if (!IsActive(instance) || !SourceExists(instance) ||
                instance.status == ReminderStatus::kSnoozed ||
                instance.status == ReminderStatus::kAttentionSilenced ||
                instance.status == ReminderStatus::kAwaitingUndo ||
                instance.status == ReminderStatus::kPresenting ||
                instance.status == ReminderStatus::kVerifyingIdentity ||
                !due_or_pre_alert) {
                continue;
            }
            if (instance.missed &&
                !PresenceContext::GetInstance().IsRadarPresent()) {
                continue;
            }
            if (!IsDeliveryGateStatus(instance.status) &&
                instance.status != ReminderStatus::kPending) {
                continue;
            }
            if (instance.status == ReminderStatus::kQueued &&
                instance.last_presented_at > 0 &&
                instance.next_attention_at > now) {
                continue;
            }
            if (IsNormalTodo(instance)) {
                if (!PresenceContext::GetInstance().IsRadarPresent() ||
                    broadcast_presence_generation_ != presence_generation ||
                    instance.deferred_presence_generation ==
                        presence_generation) {
                    continue;
                }
            }
            // Cards are visual, non-invasive acknowledgement surfaces.  A
            // due note/habit may show its first card while normal dialogue is
            // speaking; its chime/voice is deferred below.
            if (!best || Rank(instance, now) < Rank(*best, now) ||
                (Rank(instance, now) == Rank(*best, now) &&
                 instance.created_at < best->created_at)) {
                best = &instance;
            }
        }
        if (!best) {
            if (broadcast_presence_generation_ == presence_generation) {
                broadcast_presence_generation_ = 0;
            }
            return;
        }

        ESP_LOGI(kTag,
                 "[REMINDER_DELIVERY] event=due instance=%s source=%s "
                 "recipient=%s",
                 best->instance_id.c_str(),
                 SourceTypeName(best->source_type),
                 best->recipient_person_id.empty()
                     ? "-"
                     : best->recipient_person_id.c_str());

        if (RequiresPersonalDelivery(*best)) {
            bool need_verify = false;
            if (!TryBeginDeliveryLocked(*best, now, presence_generation,
                                        &need_verify)) {
                SaveLocked();
                if (need_verify) {
                    verify_target = *best;
                    request_verify = true;
                }
                // fall through after unlock
            } else {
                // Fresh confirmed identity: present now.
                const ReminderInstance best_before = *best;
                const std::string current_before = current_instance_id_;
                ReminderInstance current_before_value;
                const bool had_current = current != nullptr;
                if (had_current) current_before_value = *current;
                if (current &&
                    current->status == ReminderStatus::kPresenting) {
                    if (current->instance_id == best->instance_id) return;
                    if (Rank(*best, now) >= Rank(*current, now)) return;
                    preempted_instance_id = current->instance_id;
                    preempted_revision = current->revision;
                    if (RequiresPersonalDelivery(*current)) {
                        current->status = ReminderStatus::kWaitingRecipient;
                        current->next_identity_retry_at = now + 5;
                    } else {
                        current->status = ReminderStatus::kQueued;
                        current->next_attention_at = now;
                    }
                    current->updated_at = now;
                    AdvanceRevisionLocked(*current);
                    preempt = true;
                }
                best->status = ReminderStatus::kPresenting;
                best->last_presented_at = now;
                best->card_expires_at = now + kCardInteractionWindowSeconds;
                best->voice_deferred = !device_idle;
                best->updated_at = now;
                best->delivery_presence_generation = presence_generation;
                best->last_verified_person_id = best->recipient_person_id;
                best->bound_session_id =
                    Application::GetInstance().GetAudioSessionId();
                AdvanceRevisionLocked(*best);
                if (best->source_type == ReminderSourceType::kAlarm &&
                           best->next_attention_at == 0) {
                    best->next_attention_at = now + kAlarmRepeatSeconds;
                } else {
                    best->next_attention_at = 0;
                }
                play_chime = device_idle &&
                    best->chime_presence_generation != presence_generation;
                if (play_chime) {
                    best->chime_presence_generation = presence_generation;
                }
                request_voice = device_idle &&
                    best->voice_presence_generation != presence_generation;
                if (request_voice) {
                    best->voice_request_revision = best->voice_revision;
                    best->voice_request_at = now;
                    best->voice_presence_generation = presence_generation;
                }
                current_instance_id_ = best->instance_id;
                selected = *best;
                SaveLocked();
                if (store_dirty_) {
                    *best = best_before;
                    if (had_current && current != best) {
                        *current = current_before_value;
                    }
                    current_instance_id_ = current_before;
                    return;
                }
                have_selected = true;
            }
        } else {
            // Information cards keep the previous non-gated path.
            if (current && current->status == ReminderStatus::kPresenting) {
                if (current->instance_id == best->instance_id) return;
                if (Rank(*best, now) >= Rank(*current, now)) return;
                current->status = ReminderStatus::kQueued;
                current->next_attention_at = now;
                current->updated_at = now;
                preempted_instance_id = current->instance_id;
                preempted_revision = current->revision;
                AdvanceRevisionLocked(*current);
                preempt = true;
            }
            best->status = ReminderStatus::kPresenting;
            best->last_presented_at = now;
            best->card_expires_at = now + kCardInteractionWindowSeconds;
            best->voice_deferred = !device_idle;
            best->updated_at = now;
            best->bound_session_id =
                Application::GetInstance().GetAudioSessionId();
            AdvanceRevisionLocked(*best);
            current_instance_id_ = best->instance_id;
            if (best->source_type == ReminderSourceType::kAlarm) {
                if (best->alarm_attention_started_at == 0) {
                    best->alarm_attention_started_at = now;
                }
                best->next_attention_at = now + kAlarmRepeatSeconds;
                // Alarms are the only reminder allowed to preempt dialogue.
                play_chime = !best->missed;
                best->voice_deferred = false;
                // A missed occurrence returns as a spoken recap, not another
                // alarm ring, when somebody is next detected nearby.
                request_voice = device_idle && best->missed;
            } else {
                play_chime = device_idle;
            }
            if (request_voice) {
                best->voice_request_revision = best->voice_revision;
                best->voice_request_at = now;
                best->voice_presence_generation = presence_generation;
            }
            selected = *best;
            SaveLocked();
            have_selected = true;
        }
    }
    if (request_verify) {
        RequestIdentityVerification(verify_target);
        return;
    }
    if (!have_selected) return;
    test_observability::Event("reminder", "present",
                              presence_generation, "requested",
                              SourceTypeName(selected.source_type),
                              selected.repeat_count);
    if (preempt) {
        ReminderControlClient::GetInstance().Cancel("preempted");
        DismissVisual(preempted_instance_id, preempted_revision, "preempted");
    }
    if (selected.source_type == ReminderSourceType::kAlarm &&
        Application::GetInstance().GetDeviceState() == kDeviceStateSpeaking) {
        Application::GetInstance().AbortSpeaking(kAbortReasonNone);
    }
    if (play_chime || request_voice) {
        AnnounceDueVoice(selected, pending_count, selected.missed, play_chime);
    }
    ESP_LOGI(kTag,
             "[REMINDER_DELIVERY] event=card_show instance=%s rev=%u",
             selected.instance_id.c_str(),
             static_cast<unsigned>(selected.revision));
    Present(selected, pending_count);
}

void ReminderCoordinator::AnnounceDueVoice(const ReminderInstance& instance,
                                           size_t pending_count, bool missed,
                                           bool allow_chime) {
    auto& voice = ReminderVoiceService::GetInstance();
    if (voice.PlayDueLocalOrChime(instance, allow_chime)) {
        ESP_LOGI(kTag,
                 "[REMINDER_DELIVERY] event=due_local_play instance=%s",
                 instance.instance_id.c_str());
        return;
    }
    ESP_LOGI(kTag,
             "[REMINDER_DELIVERY] event=voice_request instance=%s "
             "recipient=%s",
             instance.instance_id.c_str(),
             instance.recipient_person_id.c_str());
    voice.RequestScripts(instance, pending_count, missed);
}

void ReminderCoordinator::Present(const ReminderInstance& instance,
                                  size_t pending_count) {
    auto* display = Board::GetInstance().GetDisplay();
    if (!display) return;
    if (instance.source_type != ReminderSourceType::kInformation &&
        !PresenceContext::GetInstance().IsRadarPresent()) {
        // Alarms still ring while nobody is nearby, but cards and details are
        // only surfaced after a later presence-time consent prompt.
        return;
    }

    const std::string visible_title = instance.title;
    const char* emotion = "reminder_attention";
    if (instance.source_type == ReminderSourceType::kHabit) {
        emotion = "happy";
    } else if (instance.source_type == ReminderSourceType::kAlarm) {
        emotion = "surprised";
    }

    auto* card = new McpCardData{};
    const char* icon = "\xef\x83\xb3";
    card->icon = strdup(icon);
    card->title = strdup(visible_title.c_str());
    const auto details = SplitDetails(instance.detail);
    for (size_t index = 0; index < details.size() && index < 4; ++index) {
        card->items[index] = strdup(details[index].c_str());
    }
    card->item_count = static_cast<int>(std::min<size_t>(details.size(), 4));
    card->status = strdup(StatusName(instance.status));
    card->auto_dismiss_ms = 0;
    card->owner_user_id = strdup(instance.owner_user_id.c_str());
    card->instance_id = strdup(instance.instance_id.c_str());
    card->revision = instance.revision;
    card->priority = strdup(PriorityName(instance.priority));
    card->primary_label = instance.action_policy.primary_label.empty()
            ? nullptr : strdup(instance.action_policy.primary_label.c_str());
    card->secondary_label = instance.action_policy.secondary_label.empty()
        ? nullptr : strdup(instance.action_policy.secondary_label.c_str());
    card->tertiary_label = instance.action_policy.tertiary_label.empty()
        ? nullptr : strdup(instance.action_policy.tertiary_label.c_str());
    card->queue_count = static_cast<int>(pending_count > 0 ? pending_count - 1 : 0);
    card->privacy_mode = false;
    display->ShowMcpCard(card);
    if (instance.source_type != ReminderSourceType::kInformation) {
        // The MCP card and its 180-second local expiry are authoritative on the
        // device.  Mirror that exact window to the service so generic chat
        // control frames cannot close a reminder action session.
        Application::GetInstance().BeginReminderInteraction(
            instance.instance_id, instance.revision, instance.card_expires_at);
    }
    // Do not overwrite an active assistant subtitle.  A due reminder is
    // represented by its card immediately; its voice waits for the normal
    // conversation playback to finish.
    display->SetEmotion(emotion);
    ESP_LOGI(kTag,
             "[REMINDER_DELIVERY] event=mcp_card_show instance=%s source=%s",
             instance.instance_id.c_str(), SourceTypeName(instance.source_type));
}

void ReminderCoordinator::DismissVisual(
    const std::string& instance_id, uint32_t revision,
    const char* interaction_reason) {
    if (interaction_reason) {
        Application::GetInstance().EndReminderInteraction(
            instance_id, revision, interaction_reason);
    }
    auto* display = Board::GetInstance().GetDisplay();
    if (display) display->DismissMcpCard(instance_id, revision);
}

void ReminderCoordinator::OnSessionClosed(
    const std::string& closed_session_id) {
    Initialize();
    {
        std::lock_guard<std::mutex> lock(mutex_);
        // A reminder card is local, durable UI.  Closing/reopening the chat
        // transport must not erase it or make its touch actions stale.
        for (auto& instance : instances_) {
            if (instance.bound_session_id.empty()) continue;
            if (!closed_session_id.empty() &&
                instance.bound_session_id != closed_session_id) {
                continue;
            }
            instance.bound_session_id.clear();
        }
        SaveLocked();
    }
}

ReminderActionResult ReminderCoordinator::Act(
    const std::string& instance_id, uint32_t expected_revision,
    ReminderAction action, int minutes, const std::string& actor_user_id,
    bool require_presented, bool touch_action, time_t snooze_at) {
    Initialize();
    ReminderActionResult result;
    ReminderInstance feedback;
    ReminderInstance before_action;
    std::string current_before;
    bool dismiss = false;
    bool source_gone = false;
    bool delete_note = false;
    bool delete_alarm = false;
    bool confirm_habit = false;
    bool reject_habit = false;
    const time_t now = time(nullptr);
    {
        std::lock_guard<std::mutex> lock(mutex_);
        ReminderInstance* instance = FindLocked(instance_id);
        if (!instance) return {false, "not_found", "提醒实例不存在", 0};
        if (require_presented &&
            (current_instance_id_ != instance_id ||
             (instance->status != ReminderStatus::kPresenting &&
              instance->status != ReminderStatus::kAwaitingUndo))) {
            return {false, "card_replaced",
                    "提醒已更新，请查看当前卡片", instance->revision};
        }
        before_action = *instance;
        current_before = current_instance_id_;

        std::string permission_error;
        const std::string actor = actor_user_id.empty() ? "default" : actor_user_id;
        // Touch actions are deliberately available to anyone nearby.  Voice
        // actions retain the normal permission and recipient checks below.
        if (!touch_action &&
            !McpCheckPermission(actor, McpPermission::kWriteReminder,
                                permission_error)) {
            return {false, "permission_denied", permission_error,
                    instance->revision};
        }
        if (!touch_action && !IsAllUsersRecipient(*instance)) {
            const std::string speaker =
                UserContext::GetInstance().GetCurrentSpeakerUserId();
            const uint32_t presence_generation =
                PresenceContext::GetInstance().PresenceGeneration();
            const bool speaker_matches =
                speaker == instance->recipient_person_id ||
                actor == instance->recipient_person_id;
            const bool face_matches = PresenceContext::GetInstance().ConfirmedMatches(
                instance->recipient_person_id, presence_generation);
            if (!speaker_matches && !face_matches) {
                return {false, "identity_mismatch", "当前不是此提醒的接收人",
                        instance->revision};
            }
        }

        // Reject actions whose card was bound to a different / closed session.
        if (!touch_action && !instance->bound_session_id.empty()) {
            const std::string current_session =
                Application::GetInstance().GetAudioSessionId();
            if (current_session.empty() ||
                current_session != instance->bound_session_id) {
                ESP_LOGW(kTag,
                         "[REMINDER_CARD] event=action_reject instance=%s "
                         "reason=session_mismatch",
                         instance->instance_id.c_str());
                return {false, "session_mismatch",
                        "会话已更新，请查看当前卡片", instance->revision};
            }
        }

        const std::string requested_action = ActionName(action);
        if (expected_revision != 0 && expected_revision != instance->revision) {
            if (instance->last_action == requested_action) {
                return {true, "already_applied", "该动作已经处理",
                        instance->revision};
            }
            return {false, "stale_revision", "提醒状态已变化，请刷新后重试",
                    instance->revision};
        }
        if (!IsActive(*instance)) {
            return {false, "inactive", "该提醒已经结束", instance->revision};
        }
        if (InvalidateMissingSourceLocked(*instance, now, nullptr, nullptr)) {
            if (current_before == instance->instance_id) {
                dismiss = true;
            }
            result.handled = true;
            result.code = "source_not_found";
            result.message = "来源事项已不存在，已关闭卡片";
            result.revision = instance->revision;
            feedback = *instance;
            SaveLocked();
            source_gone = true;
        } else if (action == ReminderAction::kUndo) {
            return {false, "unsupported_action", "提醒卡仅支持完成、稍后和不需要了",
                    instance->revision};
        } else if (action == ReminderAction::kSilenceAttention) {
            instance->status = ReminderStatus::kAttentionSilenced;
            instance->attention_silenced_until =
                now + std::max(1, minutes == 0 ? 5 : minutes) * 60;
            result.message = "已停止声音，事项仍待处理";
        } else if (instance->source_type == ReminderSourceType::kAlarm) {
            if (action == ReminderAction::kPrimary) {
                instance->status = ReminderStatus::kDismissed;
                result.message = "本次闹钟已完成";
            } else if (action == ReminderAction::kSecondary) {
                time_t next_attention_at = 0;
                int delay = 0;
                if (!ResolveSnoozeAt(now, minutes, snooze_at,
                                     next_attention_at, delay)) {
                    return {false, "invalid_snooze_time",
                            "稍后提醒需为未来一年内的时间，或1到60分钟",
                            instance->revision};
                }
                instance->status = ReminderStatus::kSnoozed;
                instance->next_attention_at = next_attention_at;
                instance->unattended_chime_emitted = false;
                instance->prompted_presence_generation = 0;
                instance->deferred_presence_generation = 0;
                result.message = snooze_at > 0
                    ? "将在指定时间再次响铃"
                    : std::to_string(delay) + "分钟后再次响铃";
            } else if (action == ReminderAction::kTertiary) {
                instance->status = ReminderStatus::kDismissed;
                delete_alarm = true;
                result.message = "闹钟已永久关闭";
            } else {
                return {false, "unsupported_action", "闹钟不支持该动作",
                        instance->revision};
            }
        } else if (instance->source_type == ReminderSourceType::kNote) {
            if (action == ReminderAction::kPrimary || action == ReminderAction::kTertiary || action == ReminderAction::kCancel) {
                instance->status = action == ReminderAction::kPrimary
                    ? ReminderStatus::kCompleted : (action == ReminderAction::kCancel
                        ? ReminderStatus::kDismissed : ReminderStatus::kSkipped);
                delete_note = true;
                result.message = action == ReminderAction::kPrimary
                    ? "提醒已完成" : (action == ReminderAction::kCancel ? "提醒已永久删除" : "已跳过本次提醒");
            } else if (action == ReminderAction::kSecondary) {
                time_t next_attention_at = 0;
                int delay = 0;
                if (!ResolveSnoozeAt(now, minutes, snooze_at,
                                     next_attention_at, delay)) {
                    return {false, "invalid_snooze_time",
                            "稍后提醒需为未来一年内的时间，或1到60分钟",
                            instance->revision};
                }
                instance->status = ReminderStatus::kSnoozed;
                instance->next_attention_at = next_attention_at;
                instance->unattended_chime_emitted = false;
                instance->prompted_presence_generation = 0;
                instance->deferred_presence_generation = 0;
                result.message = snooze_at > 0
                    ? "将在指定时间再次提醒"
                    : std::to_string(delay) + "分钟后再次提醒";
            }
        } else if (instance->source_type == ReminderSourceType::kHabit) {
            if (action == ReminderAction::kPrimary || action == ReminderAction::kTertiary) {
                instance->status = action == ReminderAction::kPrimary
                    ? ReminderStatus::kCompleted : ReminderStatus::kSkipped;
                confirm_habit = action == ReminderAction::kPrimary;
                reject_habit = action == ReminderAction::kTertiary;
                result.message = action == ReminderAction::kPrimary
                    ? "本次习惯已完成" : "已跳过今天";
            } else if (action == ReminderAction::kSecondary) {
                time_t next_attention_at = 0;
                int delay = 0;
                if (!ResolveSnoozeAt(now, minutes, snooze_at,
                                     next_attention_at, delay)) {
                    return {false, "invalid_snooze_time",
                            "稍后提醒需为未来一年内的时间，或1到60分钟",
                            instance->revision};
                }
                instance->status = ReminderStatus::kSnoozed;
                instance->next_attention_at = next_attention_at;
                instance->unattended_chime_emitted = false;
                instance->prompted_presence_generation = 0;
                instance->deferred_presence_generation = 0;
                result.message = snooze_at > 0
                    ? "将在指定时间再次提醒"
                    : std::to_string(delay) + "分钟后再次提醒";
            }
        } else {
            return {false, "not_actionable", "信息卡不可执行动作",
                    instance->revision};
        }

        if (!source_gone) {
            instance->last_action = requested_action;
            instance->updated_at = now;
            AdvanceRevisionLocked(*instance);
            result.handled = true;
            result.code = "ok";
            result.revision = instance->revision;
            feedback = *instance;
            if (current_instance_id_ == instance->instance_id) {
                current_instance_id_.clear();
                dismiss = true;
            }
            SaveLocked();
            if (store_dirty_) {
                *instance = before_action;
                current_instance_id_ = current_before;
                return {false, "storage_error", "提醒状态保存失败",
                        before_action.revision};
            }
        }
    }
    if (dismiss) {
        ReminderControlClient::GetInstance().Cancel(
            source_gone ? "source_missing" : "user_action");
        DismissVisual(before_action.instance_id,
                      before_action.revision, "resolved");
    }
    if (source_gone) {
        auto* display = Board::GetInstance().GetDisplay();
        if (display) {
            display->ShowNotification(result.message.c_str(), 2000);
            display->SetEmotion("neutral");
        }
        PresentNext(time(nullptr),
                    Application::GetInstance().GetDeviceState() ==
                        kDeviceStateIdle);
        return result;
    }
    bool source_saved = true;
    if (delete_note) source_saved = action == ReminderAction::kCancel
        ? NoteManager::GetInstance().Delete(feedback.source_id)
        : NoteManager::GetInstance().CompleteOccurrence(feedback.source_id);
    if (delete_alarm) source_saved = AlarmManager::GetInstance().Delete(feedback.source_id) && source_saved;
    if (confirm_habit) source_saved = HabitManager::GetInstance().Confirm(feedback.source_id) && source_saved;
    if (reject_habit) {
        auto rejected = HabitManager::GetInstance().Reject(feedback.source_id);
        source_saved = rejected != HabitManager::RejectResult::kStorageError &&
            rejected != HabitManager::RejectResult::kNotFound && source_saved;
    }
    if (!source_saved) {
        std::lock_guard<std::mutex> lock(mutex_);
        for (auto& instance : instances_) if (instance.instance_id == feedback.instance_id && instance.revision == feedback.revision) {
            instance = before_action; current_instance_id_ = current_before; SaveLocked(); break;
        }
        return {false, "storage_error", "事项保存失败，请重试", feedback.revision};
    }
    auto* display = Board::GetInstance().GetDisplay();
    if (display) {
        display->ShowNotification(result.message.c_str(), 2000);
        if (action == ReminderAction::kPrimary) display->SetEmotion("happy");
        else display->SetEmotion("neutral");
    }
    ReminderVoiceService::GetInstance().PlayFeedback(
        feedback, action == ReminderAction::kPrimary ? "completion" :
                  (action == ReminderAction::kTertiary || action == ReminderAction::kCancel) ? "skip" :
                  "snooze");
    if (action == ReminderAction::kPrimary ||
        action == ReminderAction::kSecondary ||
        action == ReminderAction::kTertiary || action == ReminderAction::kCancel) {
        // In an approved batch, handling the current item is the only action
        // that advances to the next one.  No separate on-screen "next" button
        // is exposed.
        PresentNext(time(nullptr),
                    Application::GetInstance().GetDeviceState() ==
                        kDeviceStateIdle);
    }
    return result;
}

ReminderActionResult ReminderCoordinator::ActCurrent(ReminderAction action,
                                                      int minutes) {
    ReminderInstance current;
    if (!GetCurrent(current)) {
        return {false, "no_current", "当前没有可操作提醒", 0};
    }
    return Act(current.instance_id, current.revision, action, minutes,
               UserContext::GetInstance().GetEffectiveUserId());
}

ReminderActionResult ReminderCoordinator::ActBySource(
    ReminderSourceType type, int source_id, ReminderAction action, int minutes,
    const std::string& actor_user_id) {
    Initialize();
    ReminderInstance existing;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        ReminderInstance* found = FindActiveBySourceLocked(type, source_id);
        if (found) existing = *found;
    }
    if (existing.instance_id.empty()) {
        const time_t now = time(nullptr);
        const std::string key = "manual-" + std::to_string(now);
        bool created = false;
        if (type == ReminderSourceType::kNote) {
            for (const auto& note : NoteManager::GetInstance().GetAll(actor_user_id)) {
                if (note.id == source_id) {
                    const std::string& creator =
                        note.creator_person_id.empty()
                            ? note.owner_user_id : note.creator_person_id;
                    created = EnqueueNote(
                        note.id, creator, note.text, now, key, note.priority,
                        note.attention_policy, note.pre_alert_minutes,
                        note.recipient_person_id, creator,
                        note.recipient_display_name_snapshot);
                    break;
                }
            }
        } else if (type == ReminderSourceType::kHabit) {
            for (const auto& habit : HabitManager::GetInstance().GetAll(actor_user_id)) {
                if (habit.id == source_id) {
                    const std::string& creator =
                        habit.creator_person_id.empty()
                            ? habit.owner_user_id : habit.creator_person_id;
                    created = EnqueueHabit(
                        habit.id, creator, habit.description, now, key,
                        habit.recipient_person_id, creator);
                    break;
                }
            }
        } else if (type == ReminderSourceType::kAlarm) {
            for (const auto& alarm : AlarmManager::GetInstance().GetAll(actor_user_id)) {
                if (alarm.id == source_id) {
                    const std::string& creator =
                        alarm.creator_person_id.empty()
                            ? alarm.owner_user_id : alarm.creator_person_id;
                    created = EnqueueAlarm(
                        alarm.id, creator, alarm.label, now, key,
                        alarm.recipient_person_id, creator);
                    break;
                }
            }
        }
        if (!created) {
            return {false, "source_not_found", "来源事项不存在或不可访问", 0};
        }
        std::lock_guard<std::mutex> lock(mutex_);
        ReminderInstance* found = FindActiveBySourceLocked(type, source_id);
        if (found) existing = *found;
    }
    return Act(existing.instance_id, existing.revision, action, minutes,
               actor_user_id);
}

bool ReminderCoordinator::GetCurrent(ReminderInstance& out) const {
    const_cast<ReminderCoordinator*>(this)->Initialize();
    std::lock_guard<std::mutex> lock(mutex_);
    if (current_instance_id_.empty()) return false;
    for (const auto& instance : instances_) {
        if (instance.instance_id == current_instance_id_ &&
            (instance.status == ReminderStatus::kPresenting ||
             instance.status == ReminderStatus::kAwaitingUndo) &&
            SourceExists(instance)) {
            out = instance;
            return true;
        }
    }
    return false;
}

bool ReminderCoordinator::GetById(const std::string& instance_id,
                                  ReminderInstance& out) const {
    const_cast<ReminderCoordinator*>(this)->Initialize();
    std::lock_guard<std::mutex> lock(mutex_);
    for (const auto& instance : instances_) {
        if (instance.instance_id == instance_id) {
            out = instance;
            return true;
        }
    }
    return false;
}

std::string ReminderCoordinator::GetCurrentJson() const {
    ReminderInstance instance;
    cJSON* root = cJSON_CreateObject();
    if (!GetCurrent(instance)) {
        cJSON_AddBoolToObject(root, "active", false);
    } else {
        const std::string actor =
            UserContext::GetInstance().GetEffectiveUserId();
        const bool can_read = CanReadDetails(instance, actor);
        // An authorized fresh read grants this exact visible version to the
        // current connection. Keep Act's session, actor and revision guards.
        const std::string session = Application::GetInstance().GetAudioSessionId();
        if (can_read && !session.empty()) {
            auto* self = const_cast<ReminderCoordinator*>(this);
            std::lock_guard<std::mutex> lock(self->mutex_);
            auto* live = self->FindLocked(instance.instance_id);
            if (live && live->revision == instance.revision &&
                self->current_instance_id_ == instance.instance_id &&
                IsActive(*live) && live->bound_session_id != session) {
                live->bound_session_id = session;
                ESP_LOGI(kTag, "[REMINDER_CARD] event=session_rebound reason=authorized_current_read revision=%u", static_cast<unsigned>(instance.revision));
            }
        }
        cJSON_AddBoolToObject(root, "active", true);
        AddString(root, "instance_id", instance.instance_id);
        cJSON_AddNumberToObject(root, "revision", instance.revision);
        cJSON_AddNumberToObject(
            root, "voice_revision", instance.voice_revision);
        AddString(root, "source_type", SourceTypeName(instance.source_type));
        AddString(root, "status", StatusName(instance.status));
        AddString(root, "priority", PriorityName(instance.priority));
        AddString(root, "title", can_read ? instance.title : "");
        AddString(root, "primary_action", instance.action_policy.primary_label);
        AddString(root, "secondary_action", instance.action_policy.secondary_label);
        AddString(root, "tertiary_action", instance.action_policy.tertiary_label);
    }
    char* text = cJSON_PrintUnformatted(root);
    std::string result = text ? text : "{\"active\":false}";
    if (text) cJSON_free(text);
    cJSON_Delete(root);
    return result;
}

std::string ReminderCoordinator::ListPendingJson(
    const std::string& actor_user_id) const {
    const_cast<ReminderCoordinator*>(this)->Initialize();
    cJSON* root = cJSON_CreateObject();
    cJSON* items = cJSON_CreateArray();
    {
        std::lock_guard<std::mutex> lock(mutex_);
        for (const auto& instance : instances_) {
            if (!IsActive(instance) || !SourceExists(instance)) continue;
            if (!CanReadDetails(instance, actor_user_id)) continue;
            cJSON* item = cJSON_CreateObject();
            AddString(item, "instance_id", instance.instance_id);
            cJSON_AddNumberToObject(item, "revision", instance.revision);
            cJSON_AddNumberToObject(
                item, "voice_revision", instance.voice_revision);
            AddString(item, "source_type", SourceTypeName(instance.source_type));
            AddString(item, "status", StatusName(instance.status));
            AddString(item, "priority", PriorityName(instance.priority));
            AddString(item, "title", instance.title);
            cJSON_AddNumberToObject(item, "due_at",
                                    static_cast<double>(instance.due_at));
            cJSON_AddItemToArray(items, item);
        }
    }
    cJSON_AddItemToObject(root, "items", items);
    char* text = cJSON_PrintUnformatted(root);
    std::string result = text ? text : "{\"items\":[]}";
    if (text) cJSON_free(text);
    cJSON_Delete(root);
    return result;
}

bool ReminderCoordinator::CanAcceptVoiceAsset(
    const std::string& instance_id,
    uint32_t voice_revision) const {
    const_cast<ReminderCoordinator*>(this)->Initialize();
    std::lock_guard<std::mutex> lock(mutex_);
    for (const auto& instance : instances_) {
        if (instance.instance_id != instance_id) continue;
        if (!IsActive(instance) || !SourceExists(instance) ||
            voice_revision == 0 ||
            voice_revision != instance.voice_revision) {
            return false;
        }
        if (!RequiresPersonalDelivery(instance)) return true;
        auto& presence = PresenceContext::GetInstance();
        if (!presence.IsRadarPresent() ||
            presence.PresenceGeneration() !=
                instance.delivery_presence_generation ||
            !presence.ConfirmedMatches(
                instance.recipient_person_id,
                instance.delivery_presence_generation) ||
            instance.status != ReminderStatus::kPresenting) {
            ESP_LOGI(kTag,
                     "[REMINDER_DELIVERY] event=voice_discard "
                     "instance=%s reason=identity_or_presence",
                     instance_id.c_str());
            return false;
        }
        return true;
    }
    return false;
}

bool ReminderCoordinator::UpdateVoiceAsset(
    const std::string& instance_id, uint32_t voice_revision,
    const ReminderVoiceAsset& asset) {
    std::lock_guard<std::mutex> lock(mutex_);
    ReminderInstance* instance = FindLocked(instance_id);
    const std::string expected_path =
        ReminderVoiceService::BuildCachePath(
            instance_id, voice_revision, asset.phase, asset.sha256);
    if (!instance || !IsActive(*instance) || voice_revision == 0 ||
        voice_revision != instance->voice_revision ||
        asset.voice_revision != voice_revision ||
        asset.cache_path != expected_path ||
        !ReminderVoiceService::IsCurrentCachePath(asset.cache_path)) {
        return false;
    }
    const auto before_instances = instances_;
    ReminderInstance updated = *instance;
    auto it = std::find_if(
        updated.voice_assets.begin(), updated.voice_assets.end(),
        [&](const ReminderVoiceAsset& current) {
            return current.phase == asset.phase;
        });
    std::vector<std::string> dropped_paths;
    if (it != updated.voice_assets.end() &&
        it->cached && !it->cache_path.empty() &&
        it->cache_path != asset.cache_path) {
        dropped_paths.push_back(it->cache_path);
    }
    if (it == updated.voice_assets.end()) {
        updated.voice_assets.push_back(asset);
    } else {
        *it = asset;
    }
    {
        auto compacted = CompactVoiceMetadata(updated);
        dropped_paths.insert(dropped_paths.end(),
                             compacted.begin(), compacted.end());
    }
    const bool retained = std::any_of(
        updated.voice_assets.begin(), updated.voice_assets.end(),
        [&](const ReminderVoiceAsset& current) {
            return current.phase == asset.phase &&
                   current.voice_revision == voice_revision &&
                   current.cache_path == asset.cache_path;
        });
    if (!retained) {
        std::remove(asset.cache_path.c_str());
        return false;
    }

    *instance = std::move(updated);
    instance->updated_at = time(nullptr);

    struct CachedRef {
        size_t instance_index;
        size_t asset_index;
    };
    auto collect_cached = [&]() {
        std::vector<CachedRef> refs;
        for (size_t instance_index = 0;
             instance_index < instances_.size(); ++instance_index) {
            for (size_t asset_index = 0;
                 asset_index <
                     instances_[instance_index].voice_assets.size();
                 ++asset_index) {
                const auto& cached =
                    instances_[instance_index].
                        voice_assets[asset_index];
                if (cached.cached && !cached.cache_path.empty()) {
                    refs.push_back(
                        {instance_index, asset_index});
                }
            }
        }
        return refs;
    };
    auto cached_refs = collect_cached();
    const size_t high_cached_count = static_cast<size_t>(
        std::count_if(
            cached_refs.begin(), cached_refs.end(),
            [&](const CachedRef& ref) {
                return instances_[ref.instance_index].priority ==
                       ReminderPriority::kHigh;
            }));
    if (instance->priority != ReminderPriority::kHigh &&
        high_cached_count >= 2 && cached_refs.size() > 2) {
        instances_ = before_instances;
        std::remove(asset.cache_path.c_str());
        return false;
    }
    while (cached_refs.size() > 2) {
        auto evict = std::find_if(
            cached_refs.begin(), cached_refs.end(),
            [&](const CachedRef& ref) {
                const auto& owner = instances_[ref.instance_index];
                const auto& cached =
                    owner.voice_assets[ref.asset_index];
                return owner.priority != ReminderPriority::kHigh &&
                       cached.cache_path != asset.cache_path;
            });
        if (evict == cached_refs.end()) {
            evict = std::find_if(
                cached_refs.begin(), cached_refs.end(),
                [&](const CachedRef& ref) {
                    return instances_[ref.instance_index].
                               voice_assets[ref.asset_index].
                               cache_path != asset.cache_path;
                });
        }
        if (evict == cached_refs.end()) {
            std::remove(asset.cache_path.c_str());
            instances_ = before_instances;
            return false;
        }
        auto& owner = instances_[evict->instance_index];
        const auto& evicted =
            owner.voice_assets[evict->asset_index];
        if (evicted.cached && !evicted.cache_path.empty()) {
            dropped_paths.push_back(evicted.cache_path);
        }
        owner.voice_assets.erase(
            owner.voice_assets.begin() + evict->asset_index);
        {
            auto compacted = CompactVoiceMetadata(owner);
            dropped_paths.insert(
                dropped_paths.end(), compacted.begin(),
                compacted.end());
        }
        cached_refs = collect_cached();
    }

    SaveLocked();
    if (store_dirty_) {
        instances_ = before_instances;
        bool new_path_preexisted = false;
        for (const auto& candidate : before_instances) {
            for (const auto& previous : candidate.voice_assets) {
                if (previous.cached &&
                    previous.cache_path == asset.cache_path) {
                    new_path_preexisted = true;
                }
            }
        }
        if (!new_path_preexisted) {
            std::remove(asset.cache_path.c_str());
        }
        return false;
    }

    for (const auto& previous_instance : before_instances) {
        for (const auto& previous : previous_instance.voice_assets) {
            if (previous.cached && !previous.cache_path.empty()) {
                dropped_paths.push_back(previous.cache_path);
            }
        }
    }
    RemoveUnreferencedCachePaths(instances_, dropped_paths);
    return true;
}

bool ReminderCoordinator::OnVisualDismissed(
    const std::string& instance_id, uint32_t revision) {
    std::lock_guard<std::mutex> lock(mutex_);
    ReminderInstance* instance = FindLocked(instance_id);
    if (!instance || instance->revision != revision ||
        instance->status != ReminderStatus::kPresenting ||
        current_instance_id_ != instance_id) {
        return false;
    }
    const ReminderInstance before = *instance;
    const std::string current_before = current_instance_id_;
    if (instance->source_type == ReminderSourceType::kInformation) {
        instance->status = ReminderStatus::kExpired;
    } else {
        instance->status = ReminderStatus::kQueued;
    }
    instance->updated_at = time(nullptr);
    AdvanceRevisionLocked(*instance);
    if (current_instance_id_ == instance_id) current_instance_id_.clear();
    SaveLocked();
    if (store_dirty_) {
        *instance = before;
        current_instance_id_ = current_before;
        return false;
    }
    return !store_dirty_;
}

bool ReminderCoordinator::RetirePerson(const std::string& person, bool legacy) {
    std::vector<std::string> paths;
    std::string dismissed; uint32_t revision = 0;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        const auto before = instances_; const auto current = current_instance_id_;
        instances_.erase(std::remove_if(instances_.begin(), instances_.end(), [&](const auto& instance) {
            const bool owned = instance.owner_user_id == person || instance.creator_person_id == person ||
                instance.recipient_person_id == person || (legacy &&
                (instance.owner_user_id.empty() || instance.owner_user_id == "default"));
            if (owned) {
                for (const auto& asset : instance.voice_assets) if (asset.cached) paths.push_back(asset.cache_path);
                if (instance.instance_id == current_instance_id_) {
                    dismissed = instance.instance_id; revision = instance.revision; current_instance_id_.clear();
                }
            }
            return owned;
        }), instances_.end());
        if (!RemoveUnreferencedCachePaths(instances_, paths)) {
            instances_ = before; current_instance_id_ = current; return false;
        }
        SaveLocked();
        if (store_dirty_) { instances_ = before; current_instance_id_ = current; return false; }
    }
    if (!dismissed.empty()) {
        ReminderControlClient::GetInstance().Cancel("identity_retired");
        DismissVisual(dismissed, revision, "identity_retired");
    }
    return true;
}

void ReminderCoordinator::RecoverLocked(time_t now) {
    current_instance_id_.clear();
    for (auto& instance : instances_) {
        if (instance.status == ReminderStatus::kPresenting ||
            instance.status == ReminderStatus::kVerifyingIdentity ||
            instance.status == ReminderStatus::kWaitingPresence ||
            instance.status == ReminderStatus::kWaitingRecipient) {
            instance.status = ReminderStatus::kQueued;
            instance.next_attention_at = now;
            instance.updated_at = now;
            AdvanceRevisionLocked(instance);
        }
        InvalidateMissingSourceLocked(instance, now, nullptr, nullptr);
    }
}

void ReminderCoordinator::LoadLocked() {
    bool saw_store_file = false;
    cJSON* root = nullptr;
    cJSON* array = nullptr;
    const char* paths[] = {kStorePath, kStoreBackupPath};
    for (const char* path : paths) {
        FILE* file = std::fopen(path, "rb");
        if (!file) continue;
        saw_store_file = true;
        std::fseek(file, 0, SEEK_END);
        const long length = std::ftell(file);
        std::rewind(file);
        if (length <= 0 ||
            length > static_cast<long>(
                kLegacyStoreReadLimitBytes)) {
            ESP_LOGE(kTag,
                     "Rejected invalid reminder store %s: %ld bytes",
                     path, length);
            std::fclose(file);
            continue;
        }
        if (length > static_cast<long>(
                kReminderStoreBudgetBytes)) {
            ESP_LOGW(
                kTag,
                "Loading oversized legacy reminder store: %ld bytes",
                length);
        }
        std::string json(static_cast<size_t>(length), '\0');
        const size_t read =
            std::fread(json.data(), 1, json.size(), file);
        std::fclose(file);
        if (read != json.size()) {
            ESP_LOGE(kTag,
                     "Short read from reminder store %s", path);
            continue;
        }
        root = cJSON_ParseWithLength(json.data(), json.size());
        if (!root) {
            ESP_LOGE(kTag,
                     "Invalid JSON in reminder store %s", path);
            continue;
        }
        array = cJSON_GetObjectItemCaseSensitive(root, "items");
        if (!cJSON_IsArray(array)) {
            array = cJSON_GetObjectItemCaseSensitive(
                root, "instances");
        }
        if (cJSON_IsArray(array)) break;
        ESP_LOGE(kTag,
                 "Missing instances array in reminder store %s", path);
        cJSON_Delete(root);
        root = nullptr;
        array = nullptr;
    }
    if (!root || !cJSON_IsArray(array)) {
        if (saw_store_file) {
            ESP_LOGE(
                kTag,
                "No valid reminder store or backup could be loaded");
        }
        return;
    }
    instances_.clear();
    std::vector<std::string> loaded_cache_paths;
    cJSON* item = nullptr;
    cJSON_ArrayForEach(item, array) {
        if (!cJSON_IsObject(item) || instances_.size() >= kMaxInstances) break;
        ReminderInstance instance;
        instance.instance_id =
            JsonStringCompat(item, "id", "instance_id");
        instance.occurrence_key =
            JsonStringCompat(item, "ok", "occurrence_key");
        if (instance.instance_id.empty()) continue;
        instance.source_type = ParseSourceType(
            JsonStringCompat(item, "src", "source_type").c_str());
        instance.source_id = static_cast<int>(
            JsonInt64Compat(item, "sid", "source_id"));
        instance.owner_user_id = JsonStringCompat(
            item, "uid", "owner_user_id", "default");
        instance.creator_person_id =
            JsonStringCompat(item, "cid", "creator_person_id");
        instance.recipient_person_id =
            JsonStringCompat(item, "rid", "recipient_person_id");
        instance.recipient_display_name_snapshot =
            JsonStringCompat(item, "rds", "recipient_display_name_snapshot");
        instance.delivery_unbound =
            JsonInt64Compat(item, "unb", "delivery_unbound") != 0;
        instance.delivery_presence_generation = static_cast<uint32_t>(
            JsonInt64Compat(item, "dpg", "delivery_presence_generation"));
        instance.last_verified_person_id =
            JsonStringCompat(item, "lvp", "last_verified_person_id");
        instance.last_delivery_attempt_at = static_cast<time_t>(
            JsonInt64Compat(item, "lda", "last_delivery_attempt_at"));
        instance.next_identity_retry_at = static_cast<time_t>(
            JsonInt64Compat(item, "nir", "next_identity_retry_at"));
        instance.reattention_count = static_cast<int>(
            JsonInt64Compat(item, "rac", "reattention_count"));
        instance.unattended_chime_emitted =
            JsonInt64Compat(item, "uce", "unattended_chime_emitted") != 0;
        instance.prompted_presence_generation = static_cast<uint32_t>(
            JsonInt64Compat(item, "ppg", "prompted_presence_generation"));
        instance.deferred_presence_generation = static_cast<uint32_t>(
            JsonInt64Compat(item, "dpg2", "deferred_presence_generation"));
        MigrateRecipientLocked(instance);
        instance.priority = ParsePriority(
            JsonStringCompat(item, "pri", "priority").c_str());
        instance.attention_policy =
            JsonStringCompat(item, "ap", "attention_policy", "general");
        instance.due_at = static_cast<time_t>(
            JsonInt64Compat(item, "due", "due_at"));
        instance.pre_alert_at = static_cast<time_t>(
            JsonInt64Compat(item, "pre", "pre_alert_at"));
        instance.next_attention_at =
            static_cast<time_t>(JsonInt64Compat(
                item, "next", "next_attention_at"));
        instance.repeat_count = static_cast<int>(
            JsonInt64Compat(item, "rep", "repeat_count"));
        instance.status = ParseStatus(
            JsonStringCompat(item, "st", "status").c_str());
        instance.revision =
            static_cast<uint32_t>(std::max<int64_t>(
                1, JsonInt64Compat(item, "rev", "revision", 1)));
        instance.voice_revision =
            static_cast<uint32_t>(std::max<int64_t>(
                1, JsonInt64Compat(
                       item, "vr", "voice_revision",
                       instance.revision)));
        instance.voice_request_revision =
            static_cast<uint32_t>(std::max<int64_t>(
                0, JsonInt64Compat(
                       item, "vrr", "voice_request_revision")));
        instance.voice_request_at = static_cast<time_t>(
            JsonInt64Compat(item, "vra", "voice_request_at"));
        instance.action_policy = PolicyFor(instance.source_type);
        instance.title = JsonStringCompat(item, "ti", "title");
        instance.detail = JsonStringCompat(item, "de", "detail");
        instance.created_at = static_cast<time_t>(
            JsonInt64Compat(item, "cr", "created_at"));
        instance.updated_at = static_cast<time_t>(
            JsonInt64Compat(item, "up", "updated_at"));
        instance.last_presented_at =
            static_cast<time_t>(JsonInt64Compat(
                item, "lp", "last_presented_at"));
        instance.card_expires_at = static_cast<time_t>(
            JsonInt64Compat(item, "ce", "card_expires_at"));
        instance.alarm_attention_started_at = static_cast<time_t>(
            JsonInt64Compat(item, "aas", "alarm_attention_started_at"));
        instance.missed = JsonInt64Compat(item, "mis", "missed") != 0;
        instance.voice_deferred =
            JsonInt64Compat(item, "vd", "voice_deferred") != 0;
        instance.attention_silenced_until =
            static_cast<time_t>(JsonInt64Compat(
                item, "asu", "attention_silenced_until"));
        instance.undo_deadline =
            static_cast<time_t>(JsonInt64Compat(
                item, "ud", "undo_deadline"));
        instance.pending_final_action = JsonStringCompat(
            item, "pfa", "pending_final_action");
        instance.last_action =
            JsonStringCompat(item, "la", "last_action");
        instance.pre_alert_script = JsonString(item, "pre_alert_script");
        instance.due_script = JsonString(item, "due_script");
        instance.repeat_script = JsonString(item, "repeat_script");
        instance.completion_script = JsonString(item, "completion_script");
        instance.snooze_script = JsonString(item, "snooze_script");
        instance.skip_script = JsonString(item, "skip_script");
        cJSON* assets = cJSON_GetObjectItemCaseSensitive(item, "va");
        if (!cJSON_IsArray(assets)) {
            assets = cJSON_GetObjectItemCaseSensitive(
                item, "voice_assets");
        }
        cJSON* asset_json = nullptr;
        cJSON_ArrayForEach(asset_json, assets) {
            ReminderVoiceAsset asset;
            asset.phase =
                JsonStringCompat(asset_json, "ph", "phase");
            asset.script =
                JsonStringCompat(asset_json, "sc", "script");
            asset.url =
                JsonStringCompat(asset_json, "u", "url");
            asset.sha256 =
                JsonStringCompat(asset_json, "sh", "sha256");
            asset.format =
                JsonStringCompat(asset_json, "f", "format");
            asset.cache_path =
                JsonStringCompat(asset_json, "cp", "cache_path");
            asset.byte_count =
                static_cast<uint32_t>(JsonInt64Compat(
                    asset_json, "b", "byte_count"));
            asset.cached = JsonInt64Compat(
                asset_json, "c", "cached") != 0;
            asset.voice_revision =
                static_cast<uint32_t>(JsonInt64Compat(
                    asset_json, "vr", "revision"));
            if (asset.cached && !asset.cache_path.empty()) {
                loaded_cache_paths.push_back(asset.cache_path);
                const std::string expected_path =
                    ReminderVoiceService::BuildCachePath(
                        instance.instance_id,
                        asset.voice_revision,
                        asset.phase,
                        asset.sha256);
                if (!ReminderVoiceService::IsCurrentCachePath(
                        asset.cache_path) ||
                    asset.cache_path != expected_path) {
                    continue;
                }
            }
            instance.voice_assets.push_back(std::move(asset));
        }
        CompactVoiceMetadata(instance);
        instances_.push_back(std::move(instance));
    }
    cJSON_Delete(root);
    for (const auto& path : loaded_cache_paths) {
        bool retained = false;
        for (const auto& instance : instances_) {
            retained = std::any_of(
                instance.voice_assets.begin(),
                instance.voice_assets.end(),
                [&](const ReminderVoiceAsset& asset) {
                    return asset.cached &&
                           asset.cache_path == path;
                });
            if (retained) break;
        }
        if (!retained) std::remove(path.c_str());
    }
    ReminderVoiceService::CleanupLegacyCacheFiles();
    DIR* directory = opendir("/userdata");
    if (directory) {
        while (dirent* entry = readdir(directory)) {
            const std::string path =
                "/userdata/" + std::string(entry->d_name);
            if (!ReminderVoiceService::IsCurrentCachePath(path)) {
                continue;
            }
            bool retained = false;
            for (const auto& instance : instances_) {
                retained = std::any_of(
                    instance.voice_assets.begin(),
                    instance.voice_assets.end(),
                    [&](const ReminderVoiceAsset& asset) {
                        return asset.cached &&
                               asset.cache_path == path;
                    });
                if (retained) break;
            }
            if (!retained) std::remove(path.c_str());
        }
        closedir(directory);
    }
    ESP_LOGI(kTag, "Loaded %u reminder instances",
             static_cast<unsigned>(instances_.size()));
}

void ReminderCoordinator::SaveLocked() {
    store_dirty_ = true;
    std::vector<ReminderInstance> persisted;
    persisted.reserve(instances_.size());
    for (const auto& instance : instances_) {
        if (IsActive(instance)) {
            persisted.push_back(instance);
            CompactPersistedText(persisted.back());
            CompactVoiceMetadata(persisted.back());
        }
    }

    std::string text = SerializeStore(persisted);
    if (text.size() > kReminderStoreBudgetBytes) {
        // Voice metadata is always expendable; active reminder core state is
        // not. First discard uncached metadata, then all voice metadata.
        for (auto& instance : persisted) {
            instance.voice_assets.erase(
                std::remove_if(
                    instance.voice_assets.begin(),
                    instance.voice_assets.end(),
                    [](const ReminderVoiceAsset& asset) {
                        return !asset.cached;
                    }),
                instance.voice_assets.end());
            CompactVoiceMetadata(instance);
        }
        ESP_LOGW(kTag,
                 "Pruning uncached voice metadata for store budget");
        text = SerializeStore(persisted);
    }
    if (text.size() > kReminderStoreBudgetBytes) {
        for (auto& instance : persisted) {
            instance.voice_assets.clear();
            CompactVoiceMetadata(instance);
        }
        ESP_LOGW(kTag,
                 "Pruning all voice metadata for store budget");
        text = SerializeStore(persisted);
    }
    if (text.empty() || text.size() > kReminderStoreBudgetBytes) {
        ESP_LOGE(
            kTag,
            "Active reminder core exceeds store budget: %u > %u",
            static_cast<unsigned>(text.size()),
            static_cast<unsigned>(kReminderStoreBudgetBytes));
        return;
    }

    std::vector<ReminderInstance> terminal;
    for (const auto& instance : instances_) {
        if (!IsActive(instance)) terminal.push_back(instance);
    }
    std::stable_sort(
        terminal.begin(), terminal.end(),
        [](const ReminderInstance& left,
           const ReminderInstance& right) {
            return left.updated_at > right.updated_at;
        });
    for (auto& instance : terminal) {
        CompactPersistedText(instance);
        instance.voice_assets.clear();
        CompactVoiceMetadata(instance);
        persisted.push_back(std::move(instance));
        std::string candidate = SerializeStore(persisted);
        if (candidate.size() > kReminderStoreBudgetBytes) {
            persisted.pop_back();
            ESP_LOGW(
                kTag,
                "Pruned older terminal reminder history at store budget");
            break;
        }
        text = std::move(candidate);
    }

    FILE* file = std::fopen(kStoreTempPath, "wb");
    if (file) {
        const bool ok =
            std::fwrite(text.data(), 1, text.size(), file) ==
                text.size() &&
                        std::fflush(file) == 0;
        std::fclose(file);
        if (ok) {
            std::remove(kStoreBackupPath);
            const bool had_store =
                std::rename(kStorePath, kStoreBackupPath) == 0;
            if (std::rename(kStoreTempPath, kStorePath) != 0) {
                if (had_store) {
                    std::rename(kStoreBackupPath, kStorePath);
                }
                ESP_LOGE(kTag, "Failed to replace reminder store");
            } else {
                std::remove(kStoreBackupPath);
                store_dirty_ = false;
            }
        } else {
            std::remove(kStoreTempPath);
            ESP_LOGE(kTag, "Failed to write reminder store");
        }
    } else {
        ESP_LOGE(kTag, "Failed to open reminder store temp file");
    }
}
