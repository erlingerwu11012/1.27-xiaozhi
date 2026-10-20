#pragma once

#include "reminder_coordinator.h"

#include <cstddef>
#include <cstdint>
#include <functional>
#include <mutex>
#include <string>

struct cJSON;

class ReminderVoiceService {
public:
    using Completion = std::function<void(bool, const ReminderVoiceAsset&,
                                          const std::string&)>;

    static ReminderVoiceService& GetInstance();

    // Tell the voice service whether this is the first item in a pending
    // batch or a non-ringing recap of a missed alarm occurrence.
    void RequestScripts(const ReminderInstance& instance,
                        size_t pending_count = 1,
                        bool missed_occurrence = false);
    void PlayAttention(const ReminderInstance& instance,
                       const std::string& phase);
    // True when this instance has a readable due-phase Ogg bound to the
    // current voice_revision.  Never matches another instance's file.
    bool HasCachedVoice(const ReminderInstance& instance,
                        const std::string& phase) const;
    // Play the instance's due cache when present.  Otherwise optionally
    // fall back to the local chime.  Returns true only when the cache played.
    bool PlayDueLocalOrChime(const ReminderInstance& instance,
                             bool allow_chime);
    void PlayFeedback(const ReminderInstance& instance,
                      const std::string& phase);
    bool CacheAssetAsync(const std::string& instance_id,
                         uint32_t voice_revision,
                         const ReminderVoiceAsset& asset, Completion completion);

    // Shared inbound handlers for main WS and ReminderControlClient.
    bool HandleIncomingAssetMessage(const cJSON* root);
    void HandleIncomingErrorMessage(const cJSON* root);

    // After a successful download + UpdateVoiceAsset, attempt one immediate
    // AI playback under the same delivery gates used by control/main paths.
    bool TryPlayAcceptedAssetNow(const std::string& instance_id,
                                 uint32_t revision,
                                 uint32_t voice_revision,
                                 const std::string& phase,
                                 uint32_t presence_generation,
                                 const std::string& recipient_person_id);

    // Shared post-cache completion for control + main WS: UpdateVoiceAsset
    // then TryPlayAcceptedAssetNow. Returns true if the asset was retained.
    bool AcceptCachedAssetAndMaybePlay(
        const std::string& instance_id, uint32_t revision,
        uint32_t voice_revision, uint32_t presence_generation,
        const std::string& recipient_person_id,
        const ReminderVoiceAsset& cached);

    static bool ValidateAsset(const ReminderVoiceAsset& asset,
                              std::string& error);
    static std::string BuildCachePath(const std::string& instance_id,
                                      uint32_t voice_revision,
                                      const std::string& phase,
                                      const std::string& sha256);
    static bool IsCurrentCachePath(const std::string& path);
    static void CleanupLegacyCacheFiles();

private:
    struct ImmediatePlayKey {
        std::string instance_id;
        uint32_t revision = 0;
        uint32_t voice_revision = 0;
        std::string phase;
        uint32_t presence_generation = 0;

        bool Matches(const ImmediatePlayKey& other) const {
            return instance_id == other.instance_id &&
                   revision == other.revision &&
                   voice_revision == other.voice_revision &&
                   phase == other.phase &&
                   presence_generation == other.presence_generation;
        }
    };

    ReminderVoiceService() = default;
    bool PlayCached(const ReminderInstance& instance,
                    const std::string& phase);
    bool PlayDownloadedFile(const ReminderVoiceAsset& asset,
                            const std::string& instance_id,
                            uint32_t voice_revision,
                            const std::string& phase);
    bool EvaluatePlayGate(const std::string& instance_id, uint32_t revision,
                          uint32_t voice_revision,
                          uint32_t presence_generation,
                          const std::string& recipient_person_id,
                          ReminderInstance* current_out,
                          const char** reason) const;
    bool ClaimImmediatePlay(const ImmediatePlayKey& key);
    void DiscardExpiredCache(const std::string& cache_path,
                             const char* reason,
                             const std::string& instance_id);

    std::mutex immediate_play_mutex_;
    bool has_immediate_play_key_ = false;
    ImmediatePlayKey last_immediate_play_;
};
