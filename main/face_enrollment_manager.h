#pragma once

#include "camera_image_buffer.h"
#include "face_enrollment_client.h"

#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

// Device-side face enrollment collection. Independent from ReminderCoordinator,
// identify, and Reminder Control. Never requests AI reminder voice.
class FaceEnrollmentManager {
public:
    enum class State : uint8_t {
        kIdle = 0,
        kWaitingForIdle,
        kCreatingSession,
        kGuidance,
        // V2 guided-burst states.  These are device-local orchestration
        // states only; server controls the next validated guidance_code.
        kAligning,
        kCapturingPose,
        kAssessing,
        kCapturing,
        kUploading,
        kDraftReady,
        kPoseFailed,
        kCancelled,
        kExpired,
        kFailed,
    };

    struct StatusSnapshot {
        State state = State::kIdle;
        int accepted_count = 0;
        int required_frames = 3;
        int attempted_frames = 0;
        std::string last_error_code;
        std::string operation_id;
        State terminal_state = State::kIdle;
    };

    struct StartResult {
        bool accepted = false;
        std::string message;
        std::string code;
    };

    static FaceEnrollmentManager& GetInstance();

    // Non-blocking. Returns user-facing tool reply text.
    StartResult StartDetailed();
    std::string Start();
    // Local cancel is immediate; remote DELETE is async and never blocks MCP.
    std::string Cancel();
    StatusSnapshot GetStatus() const;

    bool IsActive() const;
    static const char* StateName(State state);

    // Called when MCP capability is cleared/invalidated.
    void OnCapabilityCleared();

private:
    struct FinishPlan {
        State terminal = State::kIdle;
        FaceEnrollmentClient::SessionInfo cleanup_session;
        bool need_cleanup = false;
        bool release_camera = false;
        bool keep_draft_ready = false;
        const char* hint = nullptr;
        int hint_ms = 3000;
    };

    FaceEnrollmentManager() = default;

    void EnsureWorkerLocked();
    // Invalidate current generation under lock; returns session snapshot for
    // async cleanup when a remote session existed.
    FaceEnrollmentClient::SessionInfo InvalidateLocked(State terminal,
                                                       const char* error_code,
                                                       bool* had_camera);
    void ClearSessionSecretsLocked();
    void ReleaseCameraFlagLocked(bool* had_camera);
    void ReleaseCameraOutsideLock(bool held);
    void ScheduleAsyncCleanup(FaceEnrollmentClient::SessionInfo session);
    static void CleanupTaskEntry(void* arg);
    bool IsCurrentGenerationLocked(uint32_t generation) const;
    bool IsCurrentGeneration(uint32_t generation) const;
    FinishPlan BuildFinishPlanLocked(State terminal);
    // MUST be called without holding mutex_.
    void FinishOutsideLock(FinishPlan plan);
    void ShowHint(const char* text, int duration_ms = 4000);
    // V2 never displays server prose or requests service TTS.  This resolves
    // a validated state code through the local subtitle/Ogg catalog only.
    bool ShowGuidedPrompt(const char* guidance_code);
    void WorkerLoop();
    static void WorkerEntry(void* arg);
    bool AcquireCameraWithWait(uint32_t generation, int timeout_ms);
    // Returns true to continue capture loop; false => finish with terminal.
    bool HandleUploadError(const FaceEnrollmentClient::UploadResult& result,
                           uint32_t generation, State* terminal_out);
    // Runs after a V2 session has been created.  It owns the camera until any
    // terminal state, then uses the same generation-safe cleanup as V1.
    void RunGuidedWorker(uint32_t generation,
                         FaceEnrollmentClient::SessionInfo session);
    bool CaptureGuidedCandidates(uint32_t generation,
                                 CameraJpegCandidates* out);
    bool WaitGuidedPreparation(uint32_t generation, int delay_ms);
    bool PlayGuidedPromptAndPrepare(uint32_t generation,
                                    const char* guidance_code, int delay_ms);

    mutable std::mutex mutex_;
    State state_ = State::kIdle;
    uint32_t operation_generation_ = 0;
    std::string operation_id_;
    State terminal_state_ = State::kIdle;
    int accepted_count_ = 0;
    int required_frames_ = 3;
    int max_frames_ = 5;
    int attempted_frames_ = 0;
    int session_timeout_seconds_ = 120;
    std::string last_error_code_;
    FaceEnrollmentClient::SessionInfo session_;
    // Set at Start so double-tap/voice cancel use local guided feedback even
    // before CreateSession has returned a V2 SessionInfo.
    bool guided_v2_active_ = false;
    bool camera_held_ = false;
    bool stop_requested_ = false;
    bool cleanup_scheduled_ = false;
    TaskHandle_t worker_ = nullptr;
    // Uptime ms when CreateSession succeeded (local capture timeout origin).
    int64_t capture_started_at_ms_ = 0;
};
