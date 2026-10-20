#pragma once

#include <cstdint>
#include <mutex>
#include <string>

// Thread-safe radar/identity presence. Radar means "someone is present";
// confirmed_person_id is only valid after a fresh identity verification.
class PresenceContext {
public:
    static PresenceContext& GetInstance();

    static constexpr uint64_t kFreshConfirmMs = 10000;

    void SetRadarPresent(bool present);
    // Stable radar from PresenceSensor: use sensor generation (no double ++).
    void ApplyStablePresence(uint32_t generation);
    void ApplyStableAbsence();
    bool IsRadarPresent() const;
    uint32_t PresenceGeneration() const;
    uint64_t LastPresenceChangeMs() const;

    void SetConfirmedIdentity(const std::string& person_id,
                              const std::string& display_name,
                              float confidence,
                              const std::string& status,
                              uint32_t presence_generation);
    void ClearConfirmedIdentity();

    bool HasFreshConfirmedIdentity(uint32_t presence_generation) const;
    bool ConfirmedMatches(const std::string& recipient_person_id,
                          uint32_t presence_generation) const;

    std::string ConfirmedPersonId() const;
    std::string ConfirmedDisplayName() const;
    float IdentityConfidence() const;
    std::string IdentityStatus() const;
    uint32_t ConfirmedGeneration() const;
    uint64_t ConfirmedAtMs() const;

    // A product user_id is stable and user-selected.  Keep the old name as a
    // compatibility alias for existing MCP payloads and persisted records.
    static bool IsStableUserId(const std::string& id);
    static bool IsUsrPersonId(const std::string& id) {
        return IsStableUserId(id);
    }

private:
    PresenceContext() = default;

    mutable std::mutex mutex_;
    bool radar_present_ = false;
    uint32_t presence_generation_ = 0;
    uint64_t last_presence_change_ms_ = 0;

    std::string confirmed_person_id_;
    std::string confirmed_display_name_;
    uint64_t confirmed_at_ms_ = 0;
    uint32_t confirmed_generation_ = 0;
    float identity_confidence_ = 0.0f;
    std::string identity_status_;
};
