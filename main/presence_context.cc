#include "presence_context.h"

#include <esp_log.h>
#include <esp_timer.h>

namespace {
constexpr const char* kTag = "PresenceContext";

uint64_t NowMs() {
    return static_cast<uint64_t>(esp_timer_get_time() / 1000);
}
}  // namespace

PresenceContext& PresenceContext::GetInstance() {
    static PresenceContext instance;
    return instance;
}

bool PresenceContext::IsStableUserId(const std::string& id) {
    return !id.empty() && id != "all" && id != "default" && id != "guest";
}

void PresenceContext::SetRadarPresent(bool present) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (radar_present_ == present) return;
    radar_present_ = present;
    last_presence_change_ms_ = NowMs();
    if (present) {
        ++presence_generation_;
        confirmed_person_id_.clear();
        confirmed_display_name_.clear();
        confirmed_at_ms_ = 0;
        confirmed_generation_ = 0;
        identity_confidence_ = 0.0f;
        identity_status_.clear();
        ESP_LOGI(kTag,
                 "[REMINDER_DELIVERY] event=presence_generation gen=%u "
                 "radar=1",
                 static_cast<unsigned>(presence_generation_));
    } else {
        confirmed_person_id_.clear();
        confirmed_display_name_.clear();
        confirmed_at_ms_ = 0;
        confirmed_generation_ = 0;
        identity_confidence_ = 0.0f;
        identity_status_.clear();
        ESP_LOGI(kTag,
                 "[REMINDER_DELIVERY] event=presence_clear gen=%u radar=0",
                 static_cast<unsigned>(presence_generation_));
    }
}

void PresenceContext::ApplyStablePresence(uint32_t generation) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (radar_present_ && presence_generation_ == generation) {
        return;
    }
    const bool rising = !radar_present_ || presence_generation_ != generation;
    radar_present_ = true;
    presence_generation_ = generation;
    last_presence_change_ms_ = NowMs();
    if (rising) {
        confirmed_person_id_.clear();
        confirmed_display_name_.clear();
        confirmed_at_ms_ = 0;
        confirmed_generation_ = 0;
        identity_confidence_ = 0.0f;
        identity_status_.clear();
    }
    ESP_LOGI(kTag,
             "[REMINDER_DELIVERY] event=presence_generation gen=%u "
             "radar=1 source=stable_sensor",
             static_cast<unsigned>(presence_generation_));
}

void PresenceContext::ApplyStableAbsence() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!radar_present_) return;
    radar_present_ = false;
    last_presence_change_ms_ = NowMs();
    confirmed_person_id_.clear();
    confirmed_display_name_.clear();
    confirmed_at_ms_ = 0;
    confirmed_generation_ = 0;
    identity_confidence_ = 0.0f;
    identity_status_.clear();
    ESP_LOGI(kTag,
             "[REMINDER_DELIVERY] event=presence_clear gen=%u radar=0 "
             "source=stable_sensor",
             static_cast<unsigned>(presence_generation_));
}

bool PresenceContext::IsRadarPresent() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return radar_present_;
}

uint32_t PresenceContext::PresenceGeneration() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return presence_generation_;
}

uint64_t PresenceContext::LastPresenceChangeMs() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return last_presence_change_ms_;
}

void PresenceContext::SetConfirmedIdentity(
    const std::string& person_id, const std::string& display_name,
    float confidence, const std::string& status,
    uint32_t presence_generation) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!radar_present_ || presence_generation != presence_generation_) {
        return;
    }
    confirmed_person_id_ = person_id;
    confirmed_display_name_ = display_name;
    identity_confidence_ = confidence;
    identity_status_ = status;
    confirmed_generation_ = presence_generation;
    confirmed_at_ms_ = NowMs();
}

void PresenceContext::ClearConfirmedIdentity() {
    std::lock_guard<std::mutex> lock(mutex_);
    confirmed_person_id_.clear();
    confirmed_display_name_.clear();
    confirmed_at_ms_ = 0;
    confirmed_generation_ = 0;
    identity_confidence_ = 0.0f;
    identity_status_.clear();
}

bool PresenceContext::HasFreshConfirmedIdentity(
    uint32_t presence_generation) const {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!radar_present_ || presence_generation != presence_generation_ ||
        confirmed_generation_ != presence_generation_ ||
        !IsStableUserId(confirmed_person_id_)) {
        return false;
    }
    return (NowMs() - confirmed_at_ms_) <= kFreshConfirmMs;
}

bool PresenceContext::ConfirmedMatches(
    const std::string& recipient_person_id,
    uint32_t presence_generation) const {
    if (!IsStableUserId(recipient_person_id)) return false;
    std::lock_guard<std::mutex> lock(mutex_);
    if (!radar_present_ || presence_generation != presence_generation_ ||
        confirmed_generation_ != presence_generation_ ||
        confirmed_person_id_ != recipient_person_id) {
        return false;
    }
    return (NowMs() - confirmed_at_ms_) <= kFreshConfirmMs;
}

std::string PresenceContext::ConfirmedPersonId() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return confirmed_person_id_;
}

std::string PresenceContext::ConfirmedDisplayName() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return confirmed_display_name_;
}

float PresenceContext::IdentityConfidence() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return identity_confidence_;
}

std::string PresenceContext::IdentityStatus() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return identity_status_;
}

uint32_t PresenceContext::ConfirmedGeneration() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return confirmed_generation_;
}

uint64_t PresenceContext::ConfirmedAtMs() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return confirmed_at_ms_;
}
