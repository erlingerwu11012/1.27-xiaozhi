#pragma once

#include <cstdint>
#include <ctime>
#include <mutex>
#include <string>
#include <vector>

enum class ReminderSourceType {
    kAlarm,
    kNote,
    kHabit,
    kInformation,
};

enum class ReminderPriority {
    kLow,
    kNormal,
    kHigh,
};

enum class ReminderStatus {
    kPending,
    kQueued,
    kWaitingPresence,
    kVerifyingIdentity,
    kWaitingRecipient,
    kPresenting,
    kSnoozed,
    kAttentionSilenced,
    kAwaitingUndo,
    kCompleted,
    kSkipped,
    kDismissed,
    kExpired,
};

enum class ReminderAction {
    kPrimary,
    kSecondary,
    kTertiary,
    kCancel,
    kSilenceAttention,
    kUndo,
};

struct ReminderActionPolicy {
    std::string primary_label;
    std::string secondary_label;
    std::string tertiary_label;
    int default_snooze_minutes = 0;
};

struct ReminderVoiceAsset {
    std::string phase;
    std::string script;
    std::string url;
    std::string sha256;
    std::string format;
    std::string cache_path;
    uint32_t byte_count = 0;
    bool cached = false;
    uint32_t voice_revision = 0;
};

struct ReminderInstance {
    std::string instance_id;
    std::string occurrence_key;
    ReminderSourceType source_type = ReminderSourceType::kInformation;
    int source_id = 0;
    std::string owner_user_id = "default";
    // Creator may be empty for legacy rows; recipient is the only delivery key.
    std::string creator_person_id;
    std::string recipient_person_id;
    std::string recipient_display_name_snapshot;
    bool delivery_unbound = false;  // retained for migration diagnostics only
    ReminderPriority priority = ReminderPriority::kLow;
    std::string attention_policy = "general";
    time_t due_at = 0;
    time_t pre_alert_at = 0;
    time_t next_attention_at = 0;
    int repeat_count = 0;
    ReminderStatus status = ReminderStatus::kPending;
    // Card/action concurrency version. Visual lifecycle changes may advance it.
    uint32_t revision = 1;
    // Voice semantic version. Only title/detail/script input changes
    // may advance it; visual presentation must never invalidate it.
    uint32_t voice_revision = 1;
    uint32_t voice_request_revision = 0;
    time_t voice_request_at = 0;
    uint32_t delivery_presence_generation = 0;
    std::string last_verified_person_id;
    time_t last_delivery_attempt_at = 0;
    time_t next_identity_retry_at = 0;
    int reattention_count = 0;
    uint32_t chime_presence_generation = 0;
    uint32_t voice_presence_generation = 0;
    bool unattended_chime_emitted = false;
    uint32_t prompted_presence_generation = 0;
    uint32_t deferred_presence_generation = 0;
    ReminderActionPolicy action_policy;
    std::string title;
    std::string detail;
    time_t created_at = 0;
    time_t updated_at = 0;
    time_t last_presented_at = 0;
    // A reminder card is an interaction surface, not a transient subtitle.
    // It stays actionable for this bounded window and is then re-queued.
    time_t card_expires_at = 0;
    // Alarms repeat for one hour at most.  The missed bit is persisted so a
    // returning household member can be told about it without replaying it.
    time_t alarm_attention_started_at = 0;
    bool missed = false;
    bool voice_deferred = false;
    time_t attention_silenced_until = 0;
    time_t undo_deadline = 0;
    std::string pending_final_action;
    std::string last_action;
    std::string pre_alert_script;
    std::string due_script;
    std::string repeat_script;
    std::string completion_script;
    std::string snooze_script;
    std::string skip_script;
    std::vector<ReminderVoiceAsset> voice_assets;
    // WebSocket session that was active when this card was presented.
    // Empty means presented offline / idle. Cleared on session close.
    std::string bound_session_id;
    // Legacy migration marker from the former default-owner face flow.
    bool no_face_owner_bypass = false;
};

struct ReminderActionResult {
    bool handled = false;
    std::string code;
    std::string message;
    uint32_t revision = 0;
};

class ReminderCoordinator {
public:
    static ReminderCoordinator& GetInstance();

    void Initialize();
    void Tick(time_t now, bool device_idle);
    // True when a due reminder needs a presence-time prompt.
    bool HasDuePersonalReminder(time_t now) const;
    // Expose PresentNext for ProactiveWakeCoordinator reminder-first path.
    void PresentNextPublic(time_t now, bool device_idle) {
        PresentNext(now, device_idle);
    }

    bool EnqueueAlarm(int source_id, const std::string& owner,
                      const std::string& title, time_t due_at,
                      const std::string& occurrence_key,
                      const std::string& recipient_person_id = "",
                      const std::string& creator_person_id = "");
    bool EnqueueNote(int source_id, const std::string& owner,
                     const std::string& title, time_t due_at,
                     const std::string& occurrence_key,
                     const std::string& priority = "normal",
                     const std::string& attention_policy = "general",
                     int pre_alert_minutes = 0,
                     const std::string& recipient_person_id = "",
                     const std::string& creator_person_id = "",
                     const std::string& recipient_display_name = "");
    bool EnqueueHabit(int source_id, const std::string& owner,
                      const std::string& title, time_t due_at,
                      const std::string& occurrence_key,
                      const std::string& recipient_person_id = "",
                      const std::string& creator_person_id = "");

    void OnPresenceChanged(bool present);
    bool RequestPendingBroadcastPrompt(time_t now, bool long_return,
                                       time_t away_seconds = 0,
                                       const std::string& present_name = "");
    size_t PendingBroadcastCount(time_t now) const;
    void MarkPendingBroadcastPrompted(time_t now);
    bool BeginPendingBroadcast(time_t now = 0);
    bool SkipCurrentBroadcast();
    void StopPendingBroadcast();
    void RenewCurrentCardWindow(time_t now = 0);
    void OnIdentityVerificationResult(
        const std::string& instance_id, uint32_t revision,
        uint32_t presence_generation, bool confirmed,
        const std::string& reason, const std::string& verified_person_id,
        const std::string& verified_display_name);
    bool EnqueueInformation(const std::string& title,
                            const std::vector<std::string>& details,
                            uint32_t auto_dismiss_ms);

    ReminderActionResult Act(const std::string& instance_id,
                             uint32_t expected_revision,
                             ReminderAction action,
                             int minutes,
                             const std::string& actor_user_id,
                             bool require_presented = false,
                             bool touch_action = false,
                             time_t snooze_at = 0);
    ReminderActionResult ActCurrent(ReminderAction action, int minutes = 0);
    ReminderActionResult ActBySource(ReminderSourceType type, int source_id,
                                     ReminderAction action, int minutes,
                                     const std::string& actor_user_id);

    bool GetCurrent(ReminderInstance& out) const;
    bool GetById(const std::string& instance_id, ReminderInstance& out) const;
    std::string GetCurrentJson() const;
    std::string ListPendingJson(const std::string& actor_user_id) const;

    bool UpdateVoiceAsset(const std::string& instance_id,
                          uint32_t voice_revision,
                          const ReminderVoiceAsset& asset);
    bool CanAcceptVoiceAsset(const std::string& instance_id,
                             uint32_t voice_revision) const;
    ReminderActionResult CloseCurrent(const std::string& instance_id, uint32_t revision,
                                      const std::string& actor);
    void InvalidateInformation(const std::string& title_prefix, const std::string& actor);
    bool OnVisualDismissed(const std::string& instance_id, uint32_t revision);
    // Invalidate cards / presentation bound to a closed WebSocket session.
    void OnSessionClosed(const std::string& closed_session_id);
    bool RetirePerson(const std::string& person, bool legacy = false);

    static const char* SourceTypeName(ReminderSourceType type);
    static const char* StatusName(ReminderStatus status);
    static const char* PriorityName(ReminderPriority priority);
    static bool ParseAction(const std::string& value, ReminderAction& out);

private:
    ReminderCoordinator() = default;

    bool Enqueue(ReminderInstance instance);
    void LoadLocked();
    void SaveLocked();
    void RecoverLocked(time_t now);
    void FinalizeUndoLocked(ReminderInstance& instance, time_t now);
    void PresentNext(time_t now, bool device_idle);
    void Present(const ReminderInstance& instance, size_t pending_count);
    void AnnounceDueVoice(const ReminderInstance& instance,
                          size_t pending_count, bool missed,
                          bool allow_chime);
    void DismissVisual(const std::string& instance_id, uint32_t revision,
                       const char* interaction_reason = nullptr);
    int Rank(const ReminderInstance& instance, time_t now) const;
    bool IsActive(const ReminderInstance& instance) const;
    // Marks a live instance dismissed when its note/alarm/habit row is gone.
    // If it is the current card, fills dismiss_id/rev with the on-screen snapshot.
    bool InvalidateMissingSourceLocked(ReminderInstance& instance, time_t now,
                                       std::string* dismiss_id,
                                       uint32_t* dismiss_rev);
    void AdvanceRevisionLocked(ReminderInstance& instance);
    void AdvanceVoiceRevisionLocked(ReminderInstance& instance);
    void InvalidateVoiceAssetsLocked(ReminderInstance& instance);
    bool CanReadDetails(const ReminderInstance& instance,
                        const std::string& actor) const;
    bool RequiresPersonalDelivery(const ReminderInstance& instance) const;
    bool RequiresPresenceForDelivery(const ReminderInstance& instance) const;
    static bool IsAllUsersRecipient(const ReminderInstance& instance);
    static bool IsNormalTodo(const ReminderInstance& instance);
    void ApplyRecipientFields(ReminderInstance& instance,
                              const std::string& owner,
                              const std::string& recipient_person_id,
                              const std::string& creator_person_id,
                              const std::string& recipient_display_name);
    void MigrateRecipientLocked(ReminderInstance& instance);
    bool TryBeginDeliveryLocked(ReminderInstance& instance, time_t now,
                                uint32_t presence_generation,
                                bool* request_verify);
    bool AllowNoFaceOwnerBypassLocked(
        const ReminderInstance& instance) const;
    void HidePersonalCardForAbsenceLocked(time_t now,
                                          std::string* dismiss_id,
                                          uint32_t* dismiss_rev);
    void RequestIdentityVerification(const ReminderInstance& instance);
    ReminderInstance* FindLocked(const std::string& instance_id);
    ReminderInstance* FindActiveBySourceLocked(ReminderSourceType type,
                                               int source_id);

    mutable std::mutex mutex_;
    std::vector<ReminderInstance> instances_;
    std::string current_instance_id_;
    uint32_t broadcast_presence_generation_ = 0;
    bool initialized_ = false;
    bool store_dirty_ = false;
    uint32_t information_sequence_ = 0;
};
