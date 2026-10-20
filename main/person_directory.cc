#include "person_directory.h"
#include "settings.h"
#include "identity_manager.h"
#include "habit_manager.h"
#include "note_manager.h"
#include "alarm_manager.h"
#include "behavior_logger.h"
#include "reminder_coordinator.h"
#include "user_context.h"
#include <set>
#include <cstdlib>
#include <memory>

namespace {
std::string Text(const cJSON* item, const char* key) {
    auto value = cJSON_GetObjectItem(item, key);
    return cJSON_IsString(value) && value->valuestring ? value->valuestring : "";
}
uint64_t Number(const cJSON* item, const char* key) {
    auto value = cJSON_GetObjectItem(item, key);
    return cJSON_IsNumber(value) && value->valuedouble >= 0 ? value->valuedouble : 0;
}
bool Purge(const std::string& person, bool legacy = false) {
    // Evaluate every store even if an earlier one failed; retry is idempotent.
    bool okay = HabitManager::GetInstance().RetirePerson(person, legacy);
    okay = NoteManager::GetInstance().RetirePerson(person, legacy) && okay;
    okay = AlarmManager::GetInstance().RetirePerson(person, legacy) && okay;
    okay = ReminderCoordinator::GetInstance().RetirePerson(person, legacy) && okay;
    okay = BehaviorLogger::GetInstance().RetirePerson(person) && okay;
    UserContext::GetInstance().ClearCurrentSpeakerUser();
    UserContext::GetInstance().ClearSessionUserId();
    UserContext::GetInstance().ClearActiveUserId();
    UserContext::GetInstance().ClearCurrentPresentUser();
    return okay;
}
}

PersonDirectory& PersonDirectory::GetInstance() { static PersonDirectory instance; return instance; }
void PersonDirectory::Invalidate() { std::lock_guard<std::mutex> lock(mutex_); ready_ = false; }
bool PersonDirectory::Ready() const { std::lock_guard<std::mutex> lock(mutex_); return ready_; }
bool PersonDirectory::AcceptsManagement(const std::string& account, uint64_t version,
                                        const std::string& recipient) const {
    std::lock_guard<std::mutex> lock(mutex_);
    return ready_ && account == account_ && version == version_ &&
        (recipient == "all" || members_.count(recipient) != 0);
}
std::string PersonDirectory::WithManagement(const std::string& account, uint64_t version,
                                           const std::string& recipient, const std::function<std::string()>& apply) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!ready_ || account != account_ || version != version_ || (recipient != "all" && !members_.count(recipient)))
        return "{\"ok\":false,\"persisted\":false,\"error\":\"identity_mismatch\"}";
    // Directory replacement/purge and management writes use the same lock order.
    return apply();
}
bool PersonDirectory::Accepts(const PersonTurn& actor) const {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!ready_ || !actor.Eligible() || actor.account_id != account_ || actor.directory_version != version_) return false;
    if (mode_ == "default") return actor.status == "default" && actor.person_id == default_id_ && actor.generation == generation_;
    if (mode_ != "personal" || actor.status != "matched" || actor.generation != 0) return false;
    auto voice = voices_.find(actor.voiceprint_id);
    return voice != voices_.end() && voice->second.person == actor.person_id && voice->second.version == actor.template_version;
}
std::string PersonDirectory::Apply(const cJSON* state) {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto account = Text(state, "account_id"); // Java bigints may arrive as a number.
    auto account_item = cJSON_GetObjectItem(state, "account_id");
    std::string account_id = account;
    if (cJSON_IsNumber(account_item)) account_id = std::to_string(static_cast<uint64_t>(account_item->valuedouble));
    auto mode = Text(state, "mode");
    const uint64_t version = Number(state, "directory_version"), generation = Number(state, "default_generation");
    auto members = cJSON_GetObjectItem(state, "members"), tasks = cJSON_GetObjectItem(state, "cleanup_tasks");
    if (account_id.empty() || !version || !cJSON_IsArray(members) || !cJSON_IsArray(tasks) ||
        (mode != "default" && mode != "personal" && mode != "transition_pending")) return "{\"ok\":false,\"error\":\"invalid_directory\"}";
    Settings settings("person_dir", true);
    std::string persisted;
    if (settings.TryGetJson("state", &persisted) == Settings::ReadStatus::Error) return "{\"ok\":false,\"error\":\"directory_read_failed\"}";
    std::unique_ptr<cJSON, decltype(&cJSON_Delete)> old(cJSON_Parse(persisted.c_str()), cJSON_Delete);
    std::string old_account = Text(old.get(), "account_id");
    if (old_account == account_id && Number(old.get(), "directory_version") > version) return "{\"ok\":false,\"error\":\"stale_directory\"}";
    // A delayed older response must not invalidate a newer accepted catalog.
    ready_ = false;
    std::vector<UserIdentity> profiles;
    std::set<std::string> active;
    cJSON* member;
    cJSON_ArrayForEach(member, members) {
        UserIdentity profile; profile.user_id = Text(member, "user_id"); profile.display_name = Text(member, "display_name");
        if (!IsPersonId(profile.user_id) || profile.display_name.empty() || !active.insert(profile.user_id).second) return "{\"ok\":false,\"error\":\"invalid_member\"}";
        profiles.push_back(profile);
    }
    // A device transferred to another account must not retain the former account's local data.
    bool okay = true;
    if (!old_account.empty() && old_account != account_id) {
        auto old_members = cJSON_GetObjectItem(old.get(), "members");
        if (cJSON_IsArray(old_members)) {
            cJSON* previous;
            cJSON_ArrayForEach(previous, old_members) okay = Purge(Text(previous, "user_id")) && okay;
        } else {
            for (const auto& profile : IdentityManager::GetInstance().GetAll()) okay = Purge(profile.user_id) && okay;
        }
        okay = Purge("default", true) && okay;
    }
    std::map<std::string, Voice> voices;
    auto voice_items = cJSON_GetObjectItem(state, "voice_profiles");
    if (!cJSON_IsArray(voice_items)) return "{\"ok\":false,\"error\":\"invalid_voices\"}";
    cJSON* voice;
    cJSON_ArrayForEach(voice, voice_items) {
        auto id = Text(voice, "voiceprint_id"), person = Text(voice, "user_id");
        if (id.empty() || !active.count(person)) return "{\"ok\":false,\"error\":\"invalid_voice_binding\"}";
        voices[id] = {person, Number(voice, "template_version")};
    }
    cJSON* reply = cJSON_CreateObject();
    cJSON* acknowledgements = cJSON_AddArrayToObject(reply, "acknowledged");
    cJSON* task;
    cJSON_ArrayForEach(task, tasks) {
        auto id = Text(task, "id"), person = Text(task, "user_id");
        if (id.empty() || !IsPersonId(person) || active.count(person) || Number(task, "directory_version") > version) { okay = false; continue; }
        const bool cleaned = Purge(person, Number(task, "generation") > 0);
        okay = cleaned && okay;
        if (cleaned) cJSON_AddItemToArray(acknowledgements, cJSON_CreateString(id.c_str()));
    }
    // A failed store write must leave the old directory available for replay,
    // including all former members when an account transfer is retried.
    if (!okay) {
        cJSON_AddBoolToObject(reply, "ok", false);
        char* result = cJSON_PrintUnformatted(reply); std::string out = result ? result : "{\"ok\":false}";
        cJSON_free(result); cJSON_Delete(reply); return out;
    }
    // Profile replacement persists removal of retired users; late legacy APIs cannot recreate them.
    if (!IdentityManager::GetInstance().ReplaceFromServer(profiles)) {
        cJSON_Delete(reply); return "{\"ok\":false,\"error\":\"profile_write_failed\"}";
    }
    cJSON* persisted_state = cJSON_Duplicate(state, true);
    cJSON_ReplaceItemInObject(persisted_state, "account_id", cJSON_CreateString(account_id.c_str()));
    char* encoded = cJSON_PrintUnformatted(persisted_state); cJSON_Delete(persisted_state);
    if (!encoded) okay = false;
    else {
        okay = settings.SetJson("state", encoded) == ESP_OK && okay;
        okay = settings.Commit() == ESP_OK && okay; cJSON_free(encoded);
    }
    account_ = account_id; mode_ = mode; version_ = version; generation_ = generation;
    default_id_ = Text(state, "default_user_id"); voices_ = std::move(voices);
    members_.clear();
    for (const auto& profile : profiles) members_[profile.user_id] = profile.display_name;
    ready_ = okay && mode != "transition_pending";
    cJSON_AddBoolToObject(reply, "ok", okay); cJSON_AddNumberToObject(reply, "directory_version", version);
    char* result = cJSON_PrintUnformatted(reply); std::string out = result ? result : "{\"ok\":false}";
    cJSON_free(result); cJSON_Delete(reply); return out;
}
