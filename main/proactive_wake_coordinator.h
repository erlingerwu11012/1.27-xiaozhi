#pragma once

#include "face_roster.h"

#include <cstdint>
#include <ctime>
#include <functional>
#include <string>

// Central state machine for proactive wake / AI greeting / reminder delivery.
// Runs on the Application main thread (all public methods must be called there
// or via Application::Schedule).
class ProactiveWakeCoordinator {
public:
    enum class State {
        kIdle = 0,
        kConnectingForIdentity,
        kWaitingForInitialize,
        kVerifyingFace,
        kRequestingAiGreeting,
        kDeliveringReminder,
        kCancelledByAbsence,
    };

    using FaceCaptureStarter = std::function<void(uint32_t generation)>;
    using FaceCaptureCanceller = std::function<void()>;

    static ProactiveWakeCoordinator& GetInstance();

    void SetFaceCaptureHandlers(FaceCaptureStarter starter,
                                FaceCaptureCanceller canceller);

    void OnStablePresence(uint32_t generation);
    void OnStableAbsence(uint32_t generation);
    void OnFaceRosterInitialized(const std::string& session_id,
                                 FaceEnrollmentState enrollment_state);
    void OnFaceVerified(uint32_t generation,
                        const std::string& usr_id,
                        const std::string& display_name);
    void OnFaceVerificationFailed(uint32_t generation, const char* reason);
    void RequestReminderDelivery(const std::string& instance_id,
                                 uint32_t generation);

    // Called when OpenAudioChannel / session hello completes so waiting
    // initialize can bind to the current session_id.
    void OnAudioChannelReady(const std::string& session_id);
    void OnMainAudioChannelOpenFailed(const char* reason);
    void OnAudioChannelClosed();
    void CancelActiveFlow(const char* reason);
    void OnNetworkWaitTimeout();
    /** Called after proactive greeting text enters the current session downlink. */
    void OnProactiveGreetingDelivered(const std::string& session_id,
                                      uint32_t ws_request_id);
    /** Drop async greeting without entering cooldown. ws_request_id=0 ignores id filter. */
    void DiscardPendingGreeting(const char* reason, uint32_t ws_request_id = 0);
    /** True while greeting text is queued waiting for WS / session binding. */
    bool HasPendingGreeting() const;
    /** True while identity / greeting owns this presence generation's LLM turn. */
    bool IsIdentityOrGreetingInFlight() const;
    static bool IsProactiveGreetingPayload(const std::string& text);

    State GetState() const { return state_; }
    uint32_t ActiveGeneration() const { return active_generation_; }
    bool IsGreetingRateLimited() const;

    static const char* StateName(State state);

private:
    ProactiveWakeCoordinator() = default;

    bool IsGenerationLive(uint32_t generation) const;
    bool IsSessionLive(const std::string& session_id) const;
    void ResetToIdle(const char* reason);
    void BeginIdentityFlow(uint32_t generation);
    void BranchOnEnrollment(FaceEnrollmentState state);
    void RequestNoFaceGreeting();
    void RequestVerifiedFaceGreeting(const std::string& display_name);
    bool TrySendProactiveGreeting(bool verified_face,
                                  const std::string& display_name);
    bool HasPendingReminderPriority() const;
    void MarkGreetingSent();
    void ArmPendingGreeting(uint32_t generation, uint32_t ws_request_id,
                            const std::string& session_id, bool verified_face);
    void ArmInitializeTimeout();
    void CancelInitializeTimeout();
    void ArmNetworkWaitTimeout();
    void CancelNetworkWaitTimeout();

    State state_ = State::kIdle;
    uint32_t active_generation_ = 0;
    std::string active_session_id_;
    bool initialize_received_ = false;
    bool pending_reminder_after_identity_ = false;
    FaceEnrollmentState enrollment_state_ = FaceEnrollmentState::kUnknown;
    int64_t stable_absence_started_us_ = 0;
    time_t return_away_seconds_ = 0;
    bool long_return_ = false;

    // In-memory only; cleared on reboot.
    int64_t last_greeting_sent_us_ = 0;

    struct PendingGreeting {
        uint32_t presence_generation = 0;
        std::string session_id;
        uint32_t ws_request_id = 0;
        bool verified_face = false;
        bool active = false;
    };
    PendingGreeting pending_greeting_;

    FaceCaptureStarter face_capture_starter_;
    FaceCaptureCanceller face_capture_canceller_;
    void* initialize_timeout_handle_ = nullptr;
};
