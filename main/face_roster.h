#pragma once

#include <cstdint>
#include <mutex>
#include <string>

// Explicit enrollment sync state. Never treat "unset" as known-zero.
enum class FaceEnrollmentState {
    kUnknown = 0,
    kKnownZero = 1,
    kKnownOneOrMore = 2,
};

// Face template roster for reminder no-face bypass decisions.
// Server MCP initialize (current audio session) is the only source of
// known_zero / known_one_or_more counts. Local enroll may promote to
// known_one_or_more; local delete without a trusted count falls back to unknown.
class FaceRoster {
public:
    static FaceRoster& GetInstance();

    FaceEnrollmentState State() const;
    const char* StateName() const;
    // Trusted count only meaningful when state != kUnknown.
    uint32_t EnrolledCount() const;
    // Default account owner usr_* from the same initialize that set state.
    // Empty when not provided by the server (bypass must stay closed).
    std::string DefaultOwnerPersonId() const;
    std::string BoundSessionId() const;

    bool IsKnownZero() const;
    bool IsKnownOneOrMore() const;
    bool IsUnknown() const;
    // True only for kKnownOneOrMore (never true for unknown).
    bool HasAnyFaceTemplate() const;

    // Bypass is allowed only when:
    //   state == kKnownZero AND default_owner is a usr_* AND recipient matches it.
    bool AllowsNoFaceOwnerBypass(const std::string& recipient_person_id) const;

    // Reset to unknown. Used on boot (default), session open/close, and
    // untrusted local deletions.
    void MarkUnknown(const char* source);

    // Apply initialize from the *current* audio session only.
    // count_present=false → unknown (missing field / old server).
    // count < 0 → unknown (illegal).
    // count == 0 → known_zero; count > 0 → known_one_or_more.
    // default_owner_person_id may be empty; bypass stays closed until set.
    // Returns false if session_id does not match the active audio session
    // (stale initialize must not overwrite newer state).
    // On success, notifies ProactiveWakeCoordinator outside the mutex.
    bool ApplyInitialize(const std::string& session_id,
                         bool count_present,
                         int count,
                         const std::string& default_owner_person_id,
                         const char* source = "initialize");

    // Local face enrollment succeeded on-device → known_one_or_more.
    void NotifyLocalEnrollmentAccepted();

    // Local delete without a trusted remaining count → unknown.
    void NotifyLocalEnrollmentCountUntrusted(const char* source = "local_delete");

    // Bind / clear the session this roster is associated with.
    void OnAudioSessionOpened(const std::string& session_id);
    void OnAudioSessionClosed(const std::string& closed_session_id);

private:
    FaceRoster() = default;

    void LogLocked(const char* source, bool session_match) const;
    static bool IsUsrPersonId(const std::string& id);

    mutable std::mutex mutex_;
    FaceEnrollmentState state_ = FaceEnrollmentState::kUnknown;
    uint32_t enrolled_count_ = 0;
    std::string default_owner_person_id_;
    std::string bound_session_id_;
};
