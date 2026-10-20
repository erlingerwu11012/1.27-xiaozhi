#include "face_roster.h"

#include "application.h"
#include "presence_context.h"
#include "proactive_wake_coordinator.h"

#include <esp_log.h>

namespace {
constexpr const char* kTag = "FaceRoster";
}

FaceRoster& FaceRoster::GetInstance() {
    static FaceRoster instance;
    return instance;
}

bool FaceRoster::IsUsrPersonId(const std::string& id) {
    return PresenceContext::IsUsrPersonId(id);
}

const char* FaceRoster::StateName() const {
    std::lock_guard<std::mutex> lock(mutex_);
    switch (state_) {
        case FaceEnrollmentState::kKnownZero: return "known_zero";
        case FaceEnrollmentState::kKnownOneOrMore: return "known_one_or_more";
        case FaceEnrollmentState::kUnknown:
        default: return "unknown";
    }
}

FaceEnrollmentState FaceRoster::State() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return state_;
}

uint32_t FaceRoster::EnrolledCount() const {
    std::lock_guard<std::mutex> lock(mutex_);
    if (state_ == FaceEnrollmentState::kUnknown) return 0;
    return enrolled_count_;
}

std::string FaceRoster::DefaultOwnerPersonId() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return default_owner_person_id_;
}

std::string FaceRoster::BoundSessionId() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return bound_session_id_;
}

bool FaceRoster::IsKnownZero() const {
    return State() == FaceEnrollmentState::kKnownZero;
}

bool FaceRoster::IsKnownOneOrMore() const {
    return State() == FaceEnrollmentState::kKnownOneOrMore;
}

bool FaceRoster::IsUnknown() const {
    return State() == FaceEnrollmentState::kUnknown;
}

bool FaceRoster::HasAnyFaceTemplate() const {
    return IsKnownOneOrMore();
}

bool FaceRoster::AllowsNoFaceOwnerBypass(
    const std::string& recipient_person_id) const {
    std::lock_guard<std::mutex> lock(mutex_);
    if (state_ != FaceEnrollmentState::kKnownZero) return false;
    if (!IsUsrPersonId(recipient_person_id)) return false;
    if (!IsUsrPersonId(default_owner_person_id_)) return false;
    return recipient_person_id == default_owner_person_id_;
}

void FaceRoster::LogLocked(const char* source, bool session_match) const {
    const char* state_name = "unknown";
    switch (state_) {
        case FaceEnrollmentState::kKnownZero: state_name = "known_zero"; break;
        case FaceEnrollmentState::kKnownOneOrMore:
            state_name = "known_one_or_more";
            break;
        case FaceEnrollmentState::kUnknown:
        default: break;
    }
    ESP_LOGI(kTag,
             "[FACE_ROSTER] event=state_change source=%s "
             "enrollment_state=%s count=%u has_default_owner=%d "
             "session_match=%d session_len=%u",
             source ? source : "-",
             state_name,
             static_cast<unsigned>(enrolled_count_),
             IsUsrPersonId(default_owner_person_id_) ? 1 : 0,
             session_match ? 1 : 0,
             static_cast<unsigned>(bound_session_id_.size()));
}

void FaceRoster::MarkUnknown(const char* source) {
    std::lock_guard<std::mutex> lock(mutex_);
    state_ = FaceEnrollmentState::kUnknown;
    enrolled_count_ = 0;
    default_owner_person_id_.clear();
    LogLocked(source ? source : "mark_unknown", true);
}

bool FaceRoster::ApplyInitialize(const std::string& session_id,
                                 bool count_present,
                                 int count,
                                 const std::string& default_owner_person_id,
                                 const char* source) {
    const std::string current =
        Application::GetInstance().GetAudioSessionId();
    FaceEnrollmentState applied_state = FaceEnrollmentState::kUnknown;
    std::string applied_session_id;
    bool applied = false;

    {
        std::lock_guard<std::mutex> lock(mutex_);

        // Stale initialize from a previous session must not overwrite the new one.
        if (!session_id.empty() && !current.empty() && session_id != current) {
            LogLocked(source ? source : "initialize_stale", false);
            ESP_LOGW(kTag,
                     "[FACE_ROSTER] event=reject_stale_initialize "
                     "session_match=0");
            return false;
        }
        if (!current.empty()) {
            bound_session_id_ = current;
        } else if (!session_id.empty()) {
            bound_session_id_ = session_id;
        }

        if (!count_present || count < 0) {
            state_ = FaceEnrollmentState::kUnknown;
            enrolled_count_ = 0;
            default_owner_person_id_.clear();
            LogLocked(source ? source : "initialize_missing_count", true);
        } else {
            if (count == 0) {
                state_ = FaceEnrollmentState::kKnownZero;
                enrolled_count_ = 0;
            } else {
                state_ = FaceEnrollmentState::kKnownOneOrMore;
                enrolled_count_ = static_cast<uint32_t>(count);
            }

            if (IsUsrPersonId(default_owner_person_id)) {
                default_owner_person_id_ = default_owner_person_id;
            } else {
                default_owner_person_id_.clear();
            }
            LogLocked(source ? source : "initialize", true);
        }

        applied_state = state_;
        applied_session_id = bound_session_id_;
        applied = true;
    }

    // Notify wake coordinator outside the roster mutex.
    if (applied) {
        Application::GetInstance().Schedule(
            [applied_session_id, applied_state]() {
                ProactiveWakeCoordinator::GetInstance()
                    .OnFaceRosterInitialized(applied_session_id,
                                             applied_state);
            });
    }
    return true;
}

void FaceRoster::NotifyLocalEnrollmentAccepted() {
    std::lock_guard<std::mutex> lock(mutex_);
    state_ = FaceEnrollmentState::kKnownOneOrMore;
    if (enrolled_count_ == 0) {
        enrolled_count_ = 1;
    }
    LogLocked("local_enroll", true);
}

void FaceRoster::NotifyLocalEnrollmentCountUntrusted(const char* source) {
    MarkUnknown(source ? source : "local_delete");
}

void FaceRoster::OnAudioSessionOpened(const std::string& session_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    state_ = FaceEnrollmentState::kUnknown;
    enrolled_count_ = 0;
    default_owner_person_id_.clear();
    bound_session_id_ = session_id;
    LogLocked("session_opened", true);
}

void FaceRoster::OnAudioSessionClosed(const std::string& closed_session_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!closed_session_id.empty() && !bound_session_id_.empty() &&
        closed_session_id != bound_session_id_) {
        LogLocked("session_closed_other", false);
        return;
    }
    state_ = FaceEnrollmentState::kUnknown;
    enrolled_count_ = 0;
    default_owner_person_id_.clear();
    bound_session_id_.clear();
    LogLocked("session_closed", true);
}
