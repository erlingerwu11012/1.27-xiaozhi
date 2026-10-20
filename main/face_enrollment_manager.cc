#include "face_enrollment_manager.h"

#include "application.h"
#include "board.h"
#include "boards/common/esp32_camera.h"
#include "boards/esp-box-3/camera_manager.h"
#include "device_state.h"
#include "display.h"
#include "face_config_store.h"
#include "face_enrollment_prompt_catalog.h"
#include "face_roster.h"
#include "task_diagnostics.h"
#include <esp_heap_caps.h>
#include <esp_log.h>
#include <esp_timer.h>
#include <freertos/idf_additions.h>

#include <cstdio>
#include <cstring>
#include <ctime>
#include <memory>
#include <vector>

namespace {
constexpr const char* kTag = "FaceEnroll";
constexpr int kMaxTransientRetries = 3;
constexpr int kGuidedLocalTimeoutSeconds = 240;
constexpr int kGuidedCandidateCount = 3;
constexpr int kGuidedCandidateIntervalMs = 300;
constexpr int kGuidedFrontPreparationMs = 800;
constexpr int kGuidedSidePreparationMs = 1200;
constexpr int kGuidedAlignPreparationMs = 1000;
constexpr int kGuidedOrientationRetryCount = 2;

int64_t NowMs() { return esp_timer_get_time() / 1000; }

bool IsTransientCode(const std::string& code) {
    return code == "rate_limited" || code == "enrollment_busy" ||
           code == "network_error";
}

bool IsSoftQualityCode(const std::string& code) {
    return code == "no_face" || code == "multiple_faces" ||
           code == "duplicate_frame" || code == "face_quality_low";
}

bool IsFatalAuthCode(const std::string& code) {
    return code == "auth_invalid" || code == "device_mismatch" ||
           code == "account_mismatch" || code == "upload_token_invalid" ||
           code == "enrollment_disabled" || code == "capability_invalid";
}

bool IsTerminalSessionCode(const std::string& code) {
    return code == "session_expired" || code == "session_cancelled" ||
           code == "session_already_consumed" ||
           code == "upload_limit_reached";
}

bool IsGuidedAlignmentCode(const std::string& code) {
    return code == "NO_FACE" || code == "MOVE_SCREEN_LEFT" ||
           code == "MOVE_SCREEN_RIGHT" || code == "MOVE_USER_LEFT" ||
           code == "MOVE_USER_RIGHT" || code == "MOVE_UP" ||
           code == "MOVE_DOWN" || code == "MOVE_CLOSER" ||
           code == "MOVE_BACK" || code == "FACE_FORWARD" ||
           code == "TOO_DARK" || code == "MULTIPLE_FACES" ||
           code == "HOLD_STILL";
}

bool IsSidePoseGuidanceCode(const std::string& code) {
    return code == "CAPTURE_LEFT" || code == "CAPTURE_RIGHT" ||
           code == "RECAPTURE_LEFT" || code == "RECAPTURE_RIGHT";
}

const char* GuidedPoseForCode(const std::string& code) {
    if (code == "CAPTURE_FRONT" || code == "RECAPTURE_FRONT") {
        return "front";
    }
    if (code == "CAPTURE_LEFT" || code == "RECAPTURE_LEFT") return "left";
    if (code == "CAPTURE_RIGHT" || code == "RECAPTURE_RIGHT") {
        return "right";
    }
    return nullptr;
}

int GuidedPoseIndex(const char* pose) {
    if (!pose) return -1;
    if (std::strcmp(pose, "front") == 0) return 0;
    if (std::strcmp(pose, "left") == 0) return 1;
    if (std::strcmp(pose, "right") == 0) return 2;
    return -1;
}

int GuidedPreparationMs(const std::string& code) {
    return code == "CAPTURE_FRONT" ? kGuidedFrontPreparationMs
                                    : kGuidedSidePreparationMs;
}

std::string MaskSessionId(const std::string& session_id) {
    if (session_id.size() <= 8) return "****";
    return session_id.substr(0, 4) + "…" +
           session_id.substr(session_id.size() - 4);
}

struct CleanupArg {
    FaceEnrollmentClient::SessionInfo session;
};

void LogFaceTaskMemory(const char* task_name, size_t stack_bytes,
                       BaseType_t result) {
    ESP_LOGI(kTag,
             "[FACE_TASK] event=create task=%s stack_bytes=%u caps=psram|8bit "
             "result=%s internal_free=%u internal_largest=%u "
             "psram_free=%u psram_largest=%u",
             task_name ? task_name : "-", static_cast<unsigned>(stack_bytes),
             result == pdPASS ? "ok" : "failed",
             static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
             static_cast<unsigned>(heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL)),
             static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)),
             static_cast<unsigned>(heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM)));
}

// Capture an upright JPEG for enrollment.  Bounded retries when 180° rotate
// fails; never returns an orientation-untrusted frame for upload/assess.
bool CaptureEnrollmentJpeg(Esp32Camera* camera, CameraJpegBuffer* out) {
    if (!camera || !out) return false;
    out->clear();
    for (int attempt = 0; attempt <= kGuidedOrientationRetryCount; ++attempt) {
        if (!camera->Capture()) return false;
        if (!camera->LastJpegOrientationTrusted()) {
            ESP_LOGW(kTag,
                     "[FACE_ENROLL] event=orientation_untrusted "
                     "attempt=%d action=retry",
                     attempt + 1);
            continue;
        }
        *out = camera->GetLastJpeg();
        if (!out->empty()) return true;
    }
    ESP_LOGW(kTag,
             "[FACE_ENROLL] event=orientation_untrusted action=give_up");
    return false;
}
}  // namespace

FaceEnrollmentManager& FaceEnrollmentManager::GetInstance() {
    static FaceEnrollmentManager instance;
    return instance;
}

const char* FaceEnrollmentManager::StateName(State state) {
    switch (state) {
        case State::kIdle: return "idle";
        case State::kWaitingForIdle: return "waiting_for_idle";
        case State::kCreatingSession: return "creating_session";
        case State::kGuidance: return "guidance";
        case State::kAligning: return "aligning";
        case State::kCapturingPose: return "capturing_pose";
        case State::kAssessing: return "assessing";
        case State::kCapturing: return "capturing";
        case State::kUploading: return "uploading";
        case State::kDraftReady: return "draft_ready";
        case State::kPoseFailed: return "pose_failed";
        case State::kCancelled: return "cancelled";
        case State::kExpired: return "expired";
        case State::kFailed: return "failed";
    }
    return "idle";
}

bool FaceEnrollmentManager::IsActive() const {
    std::lock_guard<std::mutex> lock(mutex_);
    switch (state_) {
        case State::kWaitingForIdle:
        case State::kCreatingSession:
        case State::kGuidance:
        case State::kAligning:
        case State::kCapturingPose:
        case State::kAssessing:
        case State::kCapturing:
        case State::kUploading:
            return true;
        default:
            return false;
    }
}

FaceEnrollmentManager::StatusSnapshot FaceEnrollmentManager::GetStatus()
    const {
    std::lock_guard<std::mutex> lock(mutex_);
    StatusSnapshot snap;
    snap.state = state_;
    snap.accepted_count = accepted_count_;
    snap.required_frames = required_frames_;
    snap.attempted_frames = attempted_frames_;
    snap.last_error_code = last_error_code_;
    snap.operation_id = operation_id_;
    snap.terminal_state = terminal_state_;
    return snap;
}

void FaceEnrollmentManager::ShowHint(const char* text, int duration_ms) {
    auto* display = Board::GetInstance().GetDisplay();
    if (display && text) display->ShowNotification(text, duration_ms);
}

bool FaceEnrollmentManager::ShowGuidedPrompt(const char* guidance_code) {
    if (!guidance_code || guidance_code[0] == '\0') return false;
    // Guided prompts have priority over ordinary downlink speech.  The catalog
    // currently has empty slots, so this is dormant until local Ogg/Opus assets
    // are supplied; it must never ask the server to synthesize a fallback.
    if (Application::GetInstance().GetDeviceState() == kDeviceStateSpeaking) {
        Application::GetInstance().AbortSpeaking(kAbortReasonNone);
    }
    return FaceEnrollmentPromptCatalog::Present(guidance_code);
}

void FaceEnrollmentManager::ClearSessionSecretsLocked() {
    session_ = FaceEnrollmentClient::SessionInfo{};
}

void FaceEnrollmentManager::ReleaseCameraFlagLocked(bool* had_camera) {
    if (had_camera) *had_camera = camera_held_;
    camera_held_ = false;
}

void FaceEnrollmentManager::ReleaseCameraOutsideLock(bool held) {
    if (!held) return;
    CameraManager::GetInstance().Release();
    ESP_LOGI(kTag, "[FACE_ENROLL] event=camera_release");
}

bool FaceEnrollmentManager::IsCurrentGenerationLocked(
    uint32_t generation) const {
    return generation == operation_generation_ && !stop_requested_;
}

bool FaceEnrollmentManager::IsCurrentGeneration(uint32_t generation) const {
    std::lock_guard<std::mutex> lock(mutex_);
    return IsCurrentGenerationLocked(generation);
}

FaceEnrollmentClient::SessionInfo FaceEnrollmentManager::InvalidateLocked(
    State terminal, const char* error_code, bool* had_camera) {
    terminal_state_ = terminal;
    ++operation_generation_;
    stop_requested_ = true;
    if (error_code && error_code[0]) last_error_code_ = error_code;
    if (state_ != State::kIdle && state_ != State::kDraftReady) {
        state_ = terminal;
    } else if (state_ != State::kDraftReady) {
        state_ = terminal;
    }
    FaceEnrollmentClient::SessionInfo snap = session_;
    ClearSessionSecretsLocked();
    ReleaseCameraFlagLocked(had_camera);
    return snap;
}

void FaceEnrollmentManager::CleanupTaskEntry(void* arg) {
    task_diag::LogMemoryStage("face_enroll_cln", "cleanup_begin");
    {
        std::unique_ptr<CleanupArg> ctx(static_cast<CleanupArg*>(arg));
        std::string err;
        const bool ok = FaceEnrollmentClient::GetInstance().CancelSession(
            ctx->session, &err);
        ESP_LOGI(kTag,
                 "[FACE_ENROLL] event=session_cleanup status=%s session=%s "
                 "code=%s",
                 ok ? "ok" : "failed",
                 MaskSessionId(ctx->session.session_id).c_str(),
                 err.empty() ? "-" : err.c_str());
    }
    {
        std::lock_guard<std::mutex> lock(
            FaceEnrollmentManager::GetInstance().mutex_);
        FaceEnrollmentManager::GetInstance().cleanup_scheduled_ = false;
    }
    task_diag::LogMemoryStage("face_enroll_cln", "cleanup_end");
    vTaskDeleteWithCaps(nullptr);
}

void FaceEnrollmentManager::ScheduleAsyncCleanup(
    FaceEnrollmentClient::SessionInfo session) {
    if (session.session_id.empty() || session.cancel_url.empty()) return;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (cleanup_scheduled_) {
            ESP_LOGI(kTag,
                     "[FACE_ENROLL] event=session_cleanup status=skipped "
                     "reason=already_scheduled");
            return;
        }
        cleanup_scheduled_ = true;
    }
    auto* arg = new CleanupArg{std::move(session)};
    const BaseType_t created = xTaskCreateWithCaps(
        CleanupTaskEntry, "face_enroll_cln", 6144, arg, 2, nullptr,
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    LogFaceTaskMemory("face_enroll_cln", 6144, created);
    if (created != pdPASS) {
        delete arg;
        std::lock_guard<std::mutex> lock(mutex_);
        cleanup_scheduled_ = false;
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=session_cleanup status=failed "
                 "code=resource_exhausted");
    }
}

FaceEnrollmentManager::FinishPlan FaceEnrollmentManager::BuildFinishPlanLocked(
    State terminal) {
    FinishPlan plan;
    plan.terminal = terminal;
    terminal_state_ = terminal;
    plan.keep_draft_ready = (terminal == State::kDraftReady);
    plan.release_camera = camera_held_;
    camera_held_ = false;
    if (terminal != State::kDraftReady && !session_.session_id.empty() &&
        !cleanup_scheduled_) {
        plan.cleanup_session = session_;
        plan.need_cleanup = true;
    } else if (terminal != State::kDraftReady && cleanup_scheduled_) {
        // Cleanup already queued by Cancel()/capability clear.
        plan.need_cleanup = false;
    }
    ClearSessionSecretsLocked();
    guided_v2_active_ = false;
    if (state_ != State::kDraftReady) {
        state_ = terminal;
    }
    worker_ = nullptr;
    // Keep stop_requested_ true until idle transition so late callbacks drop.
    ESP_LOGI(kTag,
             "[FACE_ENROLL] event=session_end state=%s accepted=%d code=%s",
             StateName(state_), accepted_count_,
             last_error_code_.empty() ? "-" : last_error_code_.c_str());
    return plan;
}

void FaceEnrollmentManager::FinishOutsideLock(FinishPlan plan) {
    ReleaseCameraOutsideLock(plan.release_camera);
    if (plan.need_cleanup) {
        ScheduleAsyncCleanup(std::move(plan.cleanup_session));
    }
    if (plan.hint) ShowHint(plan.hint, plan.hint_ms);
    vTaskDelay(pdMS_TO_TICKS(50));
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!plan.keep_draft_ready &&
            (state_ == State::kCancelled || state_ == State::kExpired ||
             state_ == State::kFailed || state_ == State::kPoseFailed)) {
            state_ = State::kIdle;
            stop_requested_ = false;
        }
    }
    const char* phase = "session_end";
    if (plan.terminal == State::kCancelled) phase = "session_cancel_end";
    else if (plan.terminal == State::kFailed ||
             plan.terminal == State::kExpired ||
             plan.terminal == State::kPoseFailed) {
        phase = "session_fail_end";
    }
    task_diag::LogMemoryStage("face_enroll", phase);
}

void FaceEnrollmentManager::OnCapabilityCleared() {
    FaceEnrollmentClient::SessionInfo snap;
    bool held = false;
    bool schedule = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (state_ == State::kIdle && session_.session_id.empty()) return;
        snap = InvalidateLocked(State::kFailed, "capability_invalid", &held);
        schedule = !snap.session_id.empty();
        if (worker_ == nullptr && state_ != State::kDraftReady) {
            state_ = State::kIdle;
            stop_requested_ = false;
            // Keep cleanup_scheduled_ until async task is queued below.
        }
    }
    ReleaseCameraOutsideLock(held);
    if (schedule) ScheduleAsyncCleanup(std::move(snap));
}

void FaceEnrollmentManager::EnsureWorkerLocked() {
    if (worker_ != nullptr) return;
    stop_requested_ = false;
    cleanup_scheduled_ = false;
    ESP_LOGI(kTag, "[FACE_ENROLL] event=worker_create_begin");
    const BaseType_t created = xTaskCreateWithCaps(
        WorkerEntry, "face_enroll", 10240, this, 3, &worker_,
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    LogFaceTaskMemory("face_enroll", 10240, created);
    if (created != pdPASS) {
        worker_ = nullptr;
        state_ = State::kFailed;
        last_error_code_ = "resource_exhausted";
        terminal_state_ = State::kFailed;
        ESP_LOGE(kTag,
                 "[FACE_ENROLL] event=worker_start status=failed "
                 "code=resource_exhausted");
    }
}

FaceEnrollmentManager::StartResult FaceEnrollmentManager::StartDetailed() {
    if (!face_config::EnsureReady()) {
        ShowHint("录入服务暂不可用", 30000);
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=start status=rejected "
                 "reason=resource_exhausted");
        return {false, "录入服务暂不可用", "resource_exhausted"};
    }
    if (!FaceEnrollmentClient::GetInstance().HasValidCapability()) {
        ShowHint("录入服务暂不可用", 30000);
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=start status=rejected "
                 "reason=capability_invalid");
        return {false, "录入服务暂不可用", "capability_invalid"};
    }
    const bool guided_v2 = FaceEnrollmentClient::GetInstance().IsGuidedBurstV1();
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (state_ == State::kWaitingForIdle ||
            state_ == State::kCreatingSession ||
            state_ == State::kGuidance || state_ == State::kAligning ||
            state_ == State::kCapturingPose || state_ == State::kAssessing ||
            state_ == State::kCapturing || state_ == State::kUploading) {
            ESP_LOGI(kTag,
                     "[FACE_ENROLL] event=start status=already_active "
                     "state=%s",
                     StateName(state_));
            return {false, "already_active", "already_active"};
        }
        auto cfg = FaceEnrollmentClient::GetInstance().GetCapability();
        ++operation_generation_;
        operation_id_ = std::to_string(esp_timer_get_time());
        terminal_state_ = State::kIdle;
        state_ = State::kWaitingForIdle;
        accepted_count_ = 0;
        attempted_frames_ = 0;
        required_frames_ = cfg.required_frames;
        max_frames_ = cfg.max_frames;
        session_timeout_seconds_ = cfg.session_timeout_seconds;
        guided_v2_active_ =
            cfg.protocol_version == 2 && cfg.guided_burst_v1;
        last_error_code_.clear();
        ClearSessionSecretsLocked();
        stop_requested_ = false;
        cleanup_scheduled_ = false;
        capture_started_at_ms_ = 0;  // starts after CreateSession succeeds
        EnsureWorkerLocked();
        if (worker_ == nullptr) {
            state_ = State::kIdle;
            return {false, "录入服务暂不可用", "resource_exhausted"};
        }
    }
    Application::GetInstance().YieldConversationForFaceEnrollment();
    ShowHint("请面向设备", 4000);
    if (guided_v2) {
        ESP_LOGI(kTag, "[FACE_ENROLL] event=start status=started guided=1");
        return {true, "人脸录入已开始", "accepted"};
    }
    ESP_LOGI(kTag, "[FACE_ENROLL] event=start status=started");
    return {true, "已准备采集，请正对摄像头", "accepted"};
}

std::string FaceEnrollmentManager::Start() {
    return StartDetailed().message;
}

std::string FaceEnrollmentManager::Cancel() {
    FaceEnrollmentClient::SessionInfo snap;
    bool held = false;
    bool schedule = false;
    bool guided_v2 = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (state_ == State::kIdle && session_.session_id.empty()) {
            return "当前没有进行中的人脸采集";
        }
        guided_v2 = guided_v2_active_ || session_.guided_burst_v1;
        snap = InvalidateLocked(State::kCancelled, "session_cancelled", &held);
        schedule = !snap.session_id.empty();
        // If worker already exited, settle to idle after quick cancel.
        if (worker_ == nullptr) {
            state_ = State::kIdle;
            stop_requested_ = false;
        }
    }
    ReleaseCameraOutsideLock(held);
    if (schedule) ScheduleAsyncCleanup(std::move(snap));
    if (guided_v2) {
        ShowGuidedPrompt("CANCELLED");
    } else {
        ShowHint("采集已取消", 30000);
    }
    ESP_LOGI(kTag, "[FACE_ENROLL] event=cancelled");
    return "采集已取消";
}

bool FaceEnrollmentManager::AcquireCameraWithWait(uint32_t generation,
                                                  int timeout_ms) {
    auto& cam = CameraManager::GetInstance();
    if (cam.IsPreviewActive()) {
        std::lock_guard<std::mutex> lock(mutex_);
        last_error_code_ = "preview_active";
        return false;
    }
    if (!cam.IsStreamReady()) {
        std::lock_guard<std::mutex> lock(mutex_);
        last_error_code_ = "camera_not_ready";
        return false;
    }
    const int64_t deadline = NowMs() + timeout_ms;
    while (NowMs() < deadline) {
        if (!IsCurrentGeneration(generation)) return false;
        if (cam.IsPreviewActive()) {
            std::lock_guard<std::mutex> lock(mutex_);
            last_error_code_ = "preview_active";
            return false;
        }
        if (cam.TryAcquire()) {
            bool stale = false;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (!IsCurrentGenerationLocked(generation)) {
                    stale = true;
                } else {
                    camera_held_ = true;
                    ESP_LOGI(kTag, "[FACE_ENROLL] event=camera_acquire");
                    return true;
                }
            }
            if (stale) {
                CameraManager::GetInstance().Release();
                return false;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(150));
    }
    std::lock_guard<std::mutex> lock(mutex_);
    last_error_code_ = "camera_busy";
    return false;
}

bool FaceEnrollmentManager::HandleUploadError(
    const FaceEnrollmentClient::UploadResult& result, uint32_t generation,
    State* terminal_out) {
    if (!IsCurrentGeneration(generation)) {
        if (terminal_out) *terminal_out = State::kCancelled;
        return false;
    }
    const std::string& code = result.error_code;
    auto fail = [&](State terminal, const char* err, const char* hint) {
        bool show = false;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!IsCurrentGenerationLocked(generation)) {
                if (terminal_out) *terminal_out = State::kCancelled;
                return;
            }
            ++operation_generation_;
            stop_requested_ = true;
            state_ = terminal;
            last_error_code_ = err ? err : "network_error";
            if (terminal_out) *terminal_out = terminal;
            show = hint != nullptr;
        }
        if (show) ShowHint(hint, 30000);
    };

    if (code == "payload_too_large") {
        fail(State::kFailed, "payload_too_large", "采集失败，请重新开始");
        return false;
    }
    if (code.empty()) {
        fail(State::kFailed, "network_error", "录入服务暂不可用");
        return false;
    }
    if (code == "face_quality_low" && !result.retryable) {
        fail(State::kFailed, code.c_str(), "采集失败，请重新开始");
        return false;
    }
    if (code == "upload_limit_reached") {
        fail(State::kFailed, code.c_str(), "采集失败，请重新开始");
        return false;
    }
    if (IsTerminalSessionCode(code)) {
        const State terminal = code == "session_expired" ? State::kExpired
                                                         : State::kCancelled;
        fail(terminal, code.c_str(),
             code == "session_expired" ? "采集超时，请重试" : "采集已取消");
        return false;
    }
    if (IsFatalAuthCode(code) || code == "capability_invalid") {
        fail(State::kFailed, code.c_str(), "录入服务暂不可用");
        return false;
    }
    if (IsSoftQualityCode(code) &&
        (code != "face_quality_low" || result.retryable)) {
        if (code == "no_face") {
            ShowHint("请正对摄像头", 2500);
        } else if (code == "multiple_faces") {
            ShowHint("请确保画面中只有一个人", 2500);
        } else {
            ShowHint("请稍微转动头部", 2500);
        }
        int accepted = 0;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            accepted = accepted_count_;
        }
        ESP_LOGI(kTag,
                 "[FACE_ENROLL] event=frame_reject code=%s accepted=%d",
                 code.c_str(), accepted);
        return true;
    }
    if (IsTransientCode(code) && result.retryable) {
        return true;
    }
    fail(State::kFailed, code.c_str(), "录入服务暂不可用");
    return false;
}

bool FaceEnrollmentManager::WaitGuidedPreparation(uint32_t generation,
                                                   int delay_ms) {
    const int64_t deadline = NowMs() + delay_ms;
    while (NowMs() < deadline) {
        if (!IsCurrentGeneration(generation)) return false;
        vTaskDelay(pdMS_TO_TICKS(50));
    }
    return IsCurrentGeneration(generation);
}

bool FaceEnrollmentManager::PlayGuidedPromptAndPrepare(
    uint32_t generation, const char* guidance_code, int delay_ms) {
    if (!ShowGuidedPrompt(guidance_code)) return false;
    if (FaceEnrollmentPromptCatalog::HasAudio(guidance_code)) {
        // AudioService has no completion callback for one-shot local sounds;
        // IsPlaybackDrained is the existing completion signal.  This keeps the
        // camera idle until the prompt has really finished, while empty V2
        // placeholders return immediately in this change.
        while (!Application::GetInstance().GetAudioService().IsPlaybackDrained()) {
            if (!IsCurrentGeneration(generation)) return false;
            vTaskDelay(pdMS_TO_TICKS(25));
        }
        ESP_LOGI(kTag,
                 "[FACE_ENROLL] event=prompt_finished code=%s",
                 guidance_code);
    }
    return WaitGuidedPreparation(generation, delay_ms);
}

bool FaceEnrollmentManager::CaptureGuidedCandidates(
    uint32_t generation, CameraJpegCandidates* out) {
    if (!out) return false;
    out->clear();
    auto* camera = static_cast<Esp32Camera*>(
        CameraManager::GetInstance().GetCamera());
    if (!camera) return false;
    for (int i = 0; i < kGuidedCandidateCount; ++i) {
        if (!IsCurrentGeneration(generation)) {
            out->clear();
            return false;
        }
        task_diag::LogMemoryStage("face_enroll", "capture_begin");
        CameraJpegBuffer jpeg;
        if (!CaptureEnrollmentJpeg(camera, &jpeg)) {
            task_diag::LogMemoryStage("face_enroll", "capture_end");
            out->clear();
            return false;
        }
        task_diag::LogMemoryStage("face_enroll", "capture_end");
        out->push_back(std::move(jpeg));
        if (i + 1 < kGuidedCandidateCount) {
            if (!WaitGuidedPreparation(generation,
                                       kGuidedCandidateIntervalMs)) {
                out->clear();
                return false;
            }
        }
    }
    return out->size() >= 2 && out->size() <= 3;
}

void FaceEnrollmentManager::RunGuidedWorker(
    uint32_t generation, FaceEnrollmentClient::SessionInfo session) {
    auto finish = [this, generation](State terminal, const char* error_code,
                                     const char* prompt, bool draft_ready) {
        FinishPlan plan;
        bool emit_prompt = false;
        bool emit_draft = false;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!IsCurrentGenerationLocked(generation)) {
                // Cancelled / superseded: never emit success side-effects.
                terminal = State::kCancelled;
                prompt = nullptr;
                draft_ready = false;
                plan = BuildFinishPlanLocked(terminal);
                plan.keep_draft_ready = false;
            } else if (draft_ready) {
                // Idempotent success: a late duplicate must not re-notify or
                // re-play the draft prompt, and must not DELETE the draft.
                if (state_ == State::kDraftReady) {
                    plan = BuildFinishPlanLocked(State::kDraftReady);
                    plan.keep_draft_ready = true;
                    plan.need_cleanup = false;
                    plan.release_camera = false;
                } else {
                    state_ = State::kDraftReady;
                    ClearSessionSecretsLocked();
                    emit_draft = true;
                    emit_prompt = prompt != nullptr;
                    plan = BuildFinishPlanLocked(State::kDraftReady);
                    plan.keep_draft_ready = true;
                    plan.need_cleanup = false;
                }
            } else {
                ++operation_generation_;
                stop_requested_ = true;
                state_ = terminal;
                last_error_code_ = error_code ? error_code : "network_error";
                emit_prompt = prompt != nullptr;
                plan = BuildFinishPlanLocked(terminal);
                plan.keep_draft_ready = false;
            }
        }
        if (emit_prompt) ShowGuidedPrompt(prompt);
        if (emit_draft) FaceRoster::GetInstance().NotifyLocalEnrollmentAccepted();
        FinishOutsideLock(std::move(plan));
    };

    if (!session.guided_burst_v1) {
        finish(State::kFailed, "capability_invalid", "SERVICE_ERROR", false);
        return;
    }
    if (!AcquireCameraWithWait(generation, 15000)) {
        finish(State::kFailed, "camera_busy", "SERVICE_ERROR", false);
        return;
    }

    // Frozen at create: capability refresh must not change this worker's mode.
    const bool front_only = session.IsFrontOnlyV1();
    const bool user_relative = session.IsUserRelativeV1();
    const char* draft_prompt =
        front_only ? "DRAFT_READY_FRONT_ONLY" : "DRAFT_READY";

    int pose_rounds[3] = {0, 0, 0};
    int accepted_count = 0;
    std::string next_code = "START";
    while (true) {
        if (!IsCurrentGeneration(generation)) {
            finish(State::kCancelled, "session_cancelled", nullptr, false);
            return;
        }
        int64_t capture_started_ms = 0;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            capture_started_ms = capture_started_at_ms_;
        }
        // Use the frozen session copy for expires_at, not mutable session_.
        const int64_t expires_at = session.expires_at;
        const bool timed_out =
            (capture_started_ms > 0 &&
             NowMs() - capture_started_ms >=
                 static_cast<int64_t>(kGuidedLocalTimeoutSeconds) * 1000) ||
            (expires_at > 0 && static_cast<int64_t>(time(nullptr)) >= expires_at);
        if (timed_out) {
            finish(State::kExpired, "session_expired", "TIMEOUT", false);
            return;
        }

        if (next_code == "START") {
            if (!PlayGuidedPromptAndPrepare(
                    generation, "START", kGuidedAlignPreparationMs)) {
                finish(State::kCancelled, "session_cancelled", nullptr, false);
                return;
            }
            next_code = "ALIGNING";
            continue;
        }

        // Unnegotiated MOVE_USER_* must not be played or executed.
        if ((next_code == "MOVE_USER_LEFT" ||
             next_code == "MOVE_USER_RIGHT") &&
            !user_relative) {
            finish(State::kFailed, "user_relative_not_negotiated",
                   "UNKNOWN_RESULT", false);
            return;
        }

        // front_only sessions reject side-pose codes before any capture.
        if (front_only && IsSidePoseGuidanceCode(next_code)) {
            finish(State::kFailed, "front_only_side_pose_forbidden",
                   "UNKNOWN_RESULT", false);
            return;
        }

        if (next_code == "ALIGNING" || IsGuidedAlignmentCode(next_code)) {
            if (next_code != "ALIGNING") {
                if (!PlayGuidedPromptAndPrepare(
                        generation, next_code.c_str(),
                        kGuidedAlignPreparationMs)) {
                    finish(State::kCancelled, "session_cancelled", nullptr,
                           false);
                    return;
                }
            }
            bool stale = false;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                stale = !IsCurrentGenerationLocked(generation);
                if (!stale) state_ = State::kAligning;
            }
            if (stale) {
                finish(State::kCancelled, "session_cancelled", nullptr, false);
                return;
            }
            auto* camera = static_cast<Esp32Camera*>(
                CameraManager::GetInstance().GetCamera());
            task_diag::LogMemoryStage("face_enroll", "capture_begin");
            CameraJpegBuffer jpeg;
            if (!camera || !CaptureEnrollmentJpeg(camera, &jpeg)) {
                task_diag::LogMemoryStage("face_enroll", "capture_end");
                finish(State::kFailed, "camera_capture_failed", "SERVICE_ERROR",
                       false);
                return;
            }
            task_diag::LogMemoryStage("face_enroll", "capture_end");
            if (jpeg.empty() || !IsCurrentGeneration(generation)) {
                finish(State::kCancelled, "session_cancelled", nullptr, false);
                return;
            }
            stale = false;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                stale = !IsCurrentGenerationLocked(generation);
                if (!stale) state_ = State::kAssessing;
            }
            if (stale) {
                finish(State::kCancelled, "session_cancelled", nullptr, false);
                return;
            }
            FaceEnrollmentClient::GuidedResult result;
            const bool ok = FaceEnrollmentClient::GetInstance().AssessFrame(
                session, jpeg, &result);
            jpeg.clear();
            if (!IsCurrentGeneration(generation)) {
                finish(State::kCancelled, "session_cancelled", nullptr, false);
                return;
            }
            if (!ok) {
                finish(State::kFailed,
                       result.error_code.empty() ? "network_error"
                                                 : result.error_code.c_str(),
                       (result.error_code == "unknown_guidance_code" ||
                        result.error_code == "user_relative_not_negotiated" ||
                        result.error_code == "front_only_side_pose_forbidden" ||
                        result.error_code == "quota_full_continue_forbidden")
                           ? "UNKNOWN_RESULT"
                           : "SERVICE_ERROR",
                       false);
                return;
            }
            if (result.accepted_count < accepted_count) {
                finish(State::kFailed, "capability_invalid", "UNKNOWN_RESULT",
                       false);
                return;
            }
            accepted_count = result.accepted_count;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (IsCurrentGenerationLocked(generation)) {
                    accepted_count_ = accepted_count;
                }
            }
            // Same completion gate as capture: never treat a bare string as
            // success; ValidateGuidedResponse already enforced the triple.
            if (FaceEnrollmentClient::IsGuidedEnrollmentComplete(
                    session, result.guidance_code, result.accepted_count,
                    result.draft_ready)) {
                finish(State::kDraftReady, nullptr, draft_prompt, true);
                return;
            }
            next_code = result.guidance_code == "ALIGN_READY"
                ? "CAPTURE_FRONT" : result.guidance_code;
            continue;
        }

        const char* pose = GuidedPoseForCode(next_code);
        if (pose) {
            if (front_only && std::strcmp(pose, "front") != 0) {
                finish(State::kFailed, "front_only_side_pose_forbidden",
                       "UNKNOWN_RESULT", false);
                return;
            }
            const int pose_index = GuidedPoseIndex(pose);
            if (pose_index < 0 || pose_rounds[pose_index] >= 3) {
                finish(State::kPoseFailed, "pose_retry_limit", "POSE_FAILED",
                       false);
                return;
            }
            ++pose_rounds[pose_index];
            if (!PlayGuidedPromptAndPrepare(
                    generation, next_code.c_str(),
                    GuidedPreparationMs(next_code))) {
                finish(State::kCancelled, "session_cancelled", nullptr, false);
                return;
            }
            bool stale = false;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                stale = !IsCurrentGenerationLocked(generation);
                if (!stale) state_ = State::kCapturingPose;
            }
            if (stale) {
                finish(State::kCancelled, "session_cancelled", nullptr, false);
                return;
            }
            CameraJpegCandidates candidates;
            if (!CaptureGuidedCandidates(generation, &candidates)) {
                finish(State::kFailed, "camera_capture_failed", "SERVICE_ERROR",
                       false);
                return;
            }
            if (!PlayGuidedPromptAndPrepare(generation, "UPLOADING", 0)) {
                finish(State::kCancelled, "session_cancelled", nullptr, false);
                return;
            }
            stale = false;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                stale = !IsCurrentGenerationLocked(generation);
                if (!stale) {
                    attempted_frames_ += static_cast<int>(candidates.size());
                    state_ = State::kUploading;
                }
            }
            if (stale) {
                finish(State::kCancelled, "session_cancelled", nullptr, false);
                return;
            }
            FaceEnrollmentClient::GuidedResult result;
            const bool ok = FaceEnrollmentClient::GetInstance().CapturePose(
                session, pose, pose_rounds[pose_index], candidates, &result);
            candidates.clear();
            if (!IsCurrentGeneration(generation)) {
                finish(State::kCancelled, "session_cancelled", nullptr, false);
                return;
            }
            if (!ok) {
                finish(State::kFailed,
                       result.error_code.empty() ? "network_error"
                                                 : result.error_code.c_str(),
                       (result.error_code == "unknown_guidance_code" ||
                        result.error_code == "user_relative_not_negotiated" ||
                        result.error_code == "front_only_side_pose_forbidden" ||
                        result.error_code == "quota_full_continue_forbidden")
                           ? "UNKNOWN_RESULT"
                           : "SERVICE_ERROR",
                       false);
                return;
            }
            if (result.accepted_count < accepted_count) {
                finish(State::kFailed, "capability_invalid", "UNKNOWN_RESULT",
                       false);
                return;
            }
            accepted_count = result.accepted_count;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (IsCurrentGenerationLocked(generation)) {
                    accepted_count_ = accepted_count;
                }
            }
            if (FaceEnrollmentClient::IsGuidedEnrollmentComplete(
                    session, result.guidance_code, result.accepted_count,
                    result.draft_ready)) {
                finish(State::kDraftReady, nullptr, draft_prompt, true);
                return;
            }
            next_code = result.guidance_code;
            continue;
        }

        if (next_code == "POSE_FAILED") {
            finish(State::kPoseFailed, "pose_failed", "POSE_FAILED", false);
            return;
        }
        if (next_code == "TIMEOUT") {
            finish(State::kExpired, "session_expired", "TIMEOUT", false);
            return;
        }
        if (next_code == "CANCELLED") {
            finish(State::kCancelled, "session_cancelled", "CANCELLED", false);
            return;
        }
        if (next_code == "SERVICE_ERROR") {
            finish(State::kFailed, "service_error", "SERVICE_ERROR", false);
            return;
        }
        finish(State::kFailed, "capability_invalid", "UNKNOWN_RESULT", false);
        return;
    }
}

void FaceEnrollmentManager::WorkerEntry(void* arg) {
    auto* self = static_cast<FaceEnrollmentManager*>(arg);
    try {
        self->WorkerLoop();
    } catch (const std::bad_alloc&) {
        ESP_LOGE(kTag, "[PHOTO_PSRAM] enrollment stopped: insufficient image memory");
        FinishPlan plan;
        {
            std::lock_guard<std::mutex> lock(self->mutex_);
            self->last_error_code_ = "resource_exhausted";
            self->stop_requested_ = true;
            plan = self->BuildFinishPlanLocked(State::kFailed);
        }
        self->FinishOutsideLock(std::move(plan));
    }
    vTaskDeleteWithCaps(nullptr);
}

void FaceEnrollmentManager::WorkerLoop() {
    task_diag::LogMemoryStage("face_enroll", "worker_start");
    uint32_t generation = 0;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        generation = operation_generation_;
    }

    auto finish_with = [this](State terminal) {
        FinishPlan plan;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            plan = BuildFinishPlanLocked(terminal);
        }
        FinishOutsideLock(std::move(plan));
    };

    if (CameraManager::GetInstance().IsPreviewActive()) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (IsCurrentGenerationLocked(generation)) {
                ++operation_generation_;
                stop_requested_ = true;
                state_ = State::kFailed;
                last_error_code_ = "preview_active";
            }
        }
        ShowHint("请先关闭相机预览", 30000);
        finish_with(State::kFailed);
        return;
    }
    if (!CameraManager::GetInstance().IsStreamReady()) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (IsCurrentGenerationLocked(generation)) {
                ++operation_generation_;
                stop_requested_ = true;
                state_ = State::kFailed;
                last_error_code_ = "camera_not_ready";
            }
        }
        ShowHint("录入服务暂不可用", 30000);
        finish_with(State::kFailed);
        return;
    }

    {
        bool should_finish = false;
        std::lock_guard<std::mutex> lock(mutex_);
        if (!IsCurrentGenerationLocked(generation)) {
            should_finish = true;
        } else {
            state_ = State::kCreatingSession;
            ESP_LOGI(kTag, "[FACE_ENROLL] event=session_create_begin generation=%u",
                     static_cast<unsigned>(generation));
        }
        if (should_finish) {
            // Leave lock before finish.
        } else {
            // continue
        }
    }
    if (!IsCurrentGeneration(generation)) {
        finish_with(State::kCancelled);
        return;
    }

    FaceEnrollmentClient::SessionInfo session;
    std::string create_error;
    bool created = false;
    for (int attempt = 1; attempt <= kMaxTransientRetries; ++attempt) {
        if (!IsCurrentGeneration(generation)) {
            finish_with(State::kCancelled);
            return;
        }
        created = FaceEnrollmentClient::GetInstance().CreateSession(
            &session, &create_error);
        ESP_LOGI(kTag,
                 "[FACE_ENROLL] event=session_create_end generation=%u "
                 "status=%s code=%s",
                 static_cast<unsigned>(generation), created ? "ok" : "failed",
                 create_error.empty() ? "-" : create_error.c_str());
        if (!IsCurrentGeneration(generation)) {
            // Late success must never be accepted; best-effort DELETE once.
            if (created) {
                ScheduleAsyncCleanup(session);
            }
            finish_with(State::kCancelled);
            return;
        }
        if (created) break;
        if (!(create_error == "rate_limited" ||
              create_error == "enrollment_busy" ||
              create_error == "network_error") ||
            attempt == kMaxTransientRetries) {
            break;
        }
        ESP_LOGW(kTag, "[FACE_ENROLL] event=retry code=%s attempt=%d",
                 create_error.c_str(), attempt);
        vTaskDelay(pdMS_TO_TICKS(400 * attempt));
    }
    if (!created) {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (IsCurrentGenerationLocked(generation)) {
                ++operation_generation_;
                stop_requested_ = true;
                state_ = State::kFailed;
                last_error_code_ = create_error.empty() ? "network_error"
                                                        : create_error;
            }
        }
        ShowHint("录入服务暂不可用", 30000);
        finish_with(State::kFailed);
        return;
    }
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!IsCurrentGenerationLocked(generation)) {
            // Drop and cleanup outside.
        } else {
            session_ = session;
            required_frames_ = session.required_frames > 0
                                   ? session.required_frames
                                   : required_frames_;
            max_frames_ =
                session.max_frames > 0 ? session.max_frames : max_frames_;
            // Local collect timeout starts only after session exists.
            capture_started_at_ms_ = NowMs();
            state_ = State::kGuidance;
        }
    }
    if (!IsCurrentGeneration(generation)) {
        ScheduleAsyncCleanup(session);
        finish_with(State::kCancelled);
        return;
    }
    if (session.guided_burst_v1) {
        // V2 owns the camera for its whole guided session and never calls the
        // V1 notification/TTS path below.
        RunGuidedWorker(generation, std::move(session));
        return;
    }
    ShowHint("请正对摄像头", 3000);

    if (!AcquireCameraWithWait(generation, 15000)) {
        std::string code;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            code = last_error_code_;
            if (IsCurrentGenerationLocked(generation)) {
                ++operation_generation_;
                stop_requested_ = true;
                state_ = State::kFailed;
                if (last_error_code_.empty()) last_error_code_ = "camera_busy";
            }
        }
        if (code == "preview_active") {
            ShowHint("请先关闭相机预览", 30000);
        } else {
            ShowHint("录入服务暂不可用", 30000);
        }
        finish_with(State::kFailed);
        return;
    }

    int transient_retries = 0;
    while (true) {
        bool stop = false;
        int accepted = 0;
        int attempted = 0;
        int required = 3;
        int max_frames = 5;
        int64_t expires_at = 0;
        int local_timeout_s = 120;
        int64_t capture_started_ms = 0;
        FaceEnrollmentClient::SessionInfo session_snap;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!IsCurrentGenerationLocked(generation) ||
                state_ == State::kCancelled || state_ == State::kFailed ||
                state_ == State::kExpired) {
                stop = true;
            } else {
                accepted = accepted_count_;
                attempted = attempted_frames_;
                required = required_frames_;
                max_frames = max_frames_;
                expires_at = session_.expires_at;
                local_timeout_s = session_timeout_seconds_;
                capture_started_ms = capture_started_at_ms_;
                session_snap = session_;
                state_ = State::kGuidance;
            }
        }
        if (stop) {
            finish_with(State::kCancelled);
            return;
        }
        if (accepted >= required) {
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (!IsCurrentGenerationLocked(generation)) {
                    stop = true;
                } else {
                    state_ = State::kDraftReady;
                    // Success: do not DELETE.
                    ClearSessionSecretsLocked();
                }
            }
            if (stop) {
                finish_with(State::kCancelled);
                return;
            }
            ShowHint("采集完成，请到网页填写姓名", 30000);
            ESP_LOGI(kTag, "[FACE_ENROLL] event=draft_ready accepted=%d",
                     accepted);
            FaceRoster::GetInstance().NotifyLocalEnrollmentAccepted();
            FinishPlan plan;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                plan = BuildFinishPlanLocked(State::kDraftReady);
                plan.keep_draft_ready = true;
                plan.need_cleanup = false;
            }
            FinishOutsideLock(std::move(plan));
            return;
        }
        if (attempted >= max_frames) {
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (IsCurrentGenerationLocked(generation)) {
                    ++operation_generation_;
                    stop_requested_ = true;
                    state_ = State::kFailed;
                    last_error_code_ = "upload_limit_reached";
                }
            }
            ShowHint("采集失败，请重新开始", 30000);
            finish_with(State::kFailed);
            return;
        }
        // expires_at is Unix seconds; compare with time(nullptr), never with
        // esp_timer uptime (NowMs()). Local timeout uses capture_started_at_ms_.
        const int64_t now_unix = static_cast<int64_t>(time(nullptr));
        const int64_t capture_elapsed_ms =
            capture_started_ms > 0 ? (NowMs() - capture_started_ms) : 0;
        if ((expires_at > 0 && now_unix >= expires_at) ||
            (capture_started_ms > 0 &&
             capture_elapsed_ms >
                 static_cast<int64_t>(local_timeout_s) * 1000)) {
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (IsCurrentGenerationLocked(generation)) {
                    ++operation_generation_;
                    stop_requested_ = true;
                    state_ = State::kExpired;
                    last_error_code_ = "session_expired";
                }
            }
            ShowHint("采集超时，请重试", 30000);
            finish_with(State::kExpired);
            return;
        }

        char progress[48];
        std::snprintf(progress, sizeof(progress), "正在采集 %d/%d",
                      accepted + 1, required);
        ShowHint(progress, 2500);
        if (accepted > 0) ShowHint("请稍微转动头部", 2500);

        {
            bool cancel_now = false;
            std::lock_guard<std::mutex> lock(mutex_);
            if (!IsCurrentGenerationLocked(generation)) {
                cancel_now = true;
            } else {
                state_ = State::kCapturing;
            }
            if (cancel_now) {
                // unlock then finish
            }
        }
        if (!IsCurrentGeneration(generation)) {
            finish_with(State::kCancelled);
            return;
        }

        auto& cam = CameraManager::GetInstance();
        auto* camera = static_cast<Esp32Camera*>(cam.GetCamera());
        task_diag::LogMemoryStage("face_enroll", "capture_begin");
        if (!camera || !camera->Capture()) {
            task_diag::LogMemoryStage("face_enroll", "capture_end");
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (IsCurrentGenerationLocked(generation)) {
                    ++operation_generation_;
                    stop_requested_ = true;
                    state_ = State::kFailed;
                    last_error_code_ = camera ? "capture_failed" : "camera_unavailable";
                }
            }
            ShowHint(camera ? "拍照失败，请稍后再试" : "摄像头不可用", 30000);
            finish_with(State::kFailed);
            return;
        }
        task_diag::LogMemoryStage("face_enroll", "capture_end");
        if (!IsCurrentGeneration(generation)) {
            finish_with(State::kCancelled);
            return;
        }

        CameraJpegBuffer jpeg = camera->GetLastJpeg();
        ESP_LOGI(kTag,
                 "[FACE_ENROLL] event=capture_done generation=%u bytes=%u",
                 static_cast<unsigned>(generation),
                 static_cast<unsigned>(jpeg.size()));
        int previous_accepted = 0;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!IsCurrentGenerationLocked(generation)) {
                jpeg.clear();
            } else {
                ++attempted_frames_;
                state_ = State::kUploading;
                session_snap = session_;
                previous_accepted = accepted_count_;
            }
        }
        if (!IsCurrentGeneration(generation)) {
            jpeg.clear();
            finish_with(State::kCancelled);
            return;
        }
        if (jpeg.empty()) {
            ShowHint("请正对摄像头", 2500);
            continue;
        }

        FaceEnrollmentClient::UploadResult result;
        const bool ok = FaceEnrollmentClient::GetInstance().UploadFrame(
            session_snap, jpeg, previous_accepted, &result);
        ESP_LOGI(kTag,
                 "[FACE_ENROLL] event=upload_done generation=%u ok=%d status=%s code=%s accepted=%d",
                 static_cast<unsigned>(generation), ok ? 1 : 0,
                 result.status.c_str(), result.error_code.c_str(),
                 result.accepted_count);
        jpeg.clear();
        jpeg.shrink_to_fit();

        if (!IsCurrentGeneration(generation)) {
            // Stale success/draft_ready must never update UI/state.
            ESP_LOGI(kTag,
                     "[FACE_ENROLL] event=frame_discard reason=stale_generation");
            finish_with(State::kCancelled);
            return;
        }

        if (ok) {
            transient_retries = 0;
            bool draft = false;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (!IsCurrentGenerationLocked(generation)) {
                    draft = false;
                } else {
                    accepted_count_ = result.accepted_count;
                    if (result.required_frames > 0) {
                        required_frames_ = result.required_frames;
                    }
                    draft = result.draft_ready || result.status == "draft_ready";
                    if (draft) {
                        state_ = State::kDraftReady;
                        ClearSessionSecretsLocked();
                    }
                }
            }
            if (!IsCurrentGeneration(generation) && !draft) {
                finish_with(State::kCancelled);
                return;
            }
            if (draft) {
                FaceRoster::GetInstance().NotifyLocalEnrollmentAccepted();
                // Re-check: Cancel may have raced; only show draft if still
                // marked draft_ready under lock.
                bool still_draft = false;
                {
                    std::lock_guard<std::mutex> lock(mutex_);
                    still_draft = (state_ == State::kDraftReady);
                }
                if (!still_draft) {
                    finish_with(State::kCancelled);
                    return;
                }
                ShowHint("采集完成，请到网页填写姓名", 30000);
                ESP_LOGI(kTag,
                         "[FACE_ENROLL] event=draft_ready accepted=%d",
                         result.accepted_count);
                FinishPlan plan;
                {
                    std::lock_guard<std::mutex> lock(mutex_);
                    plan = BuildFinishPlanLocked(State::kDraftReady);
                    plan.keep_draft_ready = true;
                    plan.need_cleanup = false;
                }
                FinishOutsideLock(std::move(plan));
                return;
            }
            continue;
        }

        if (result.error_code == "payload_too_large") {
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (IsCurrentGenerationLocked(generation)) {
                    ++operation_generation_;
                    stop_requested_ = true;
                    state_ = State::kFailed;
                    last_error_code_ = "payload_too_large";
                }
            }
            ShowHint("采集失败，请重新开始", 30000);
            finish_with(State::kFailed);
            return;
        }

        if (IsTransientCode(result.error_code) && result.retryable) {
            ++transient_retries;
            if (transient_retries > kMaxTransientRetries) {
                {
                    std::lock_guard<std::mutex> lock(mutex_);
                    if (IsCurrentGenerationLocked(generation)) {
                        ++operation_generation_;
                        stop_requested_ = true;
                        state_ = State::kFailed;
                        last_error_code_ = result.error_code;
                    }
                }
                ShowHint("录入服务暂不可用", 30000);
                finish_with(State::kFailed);
                return;
            }
            if (!IsCurrentGeneration(generation)) {
                finish_with(State::kCancelled);
                return;
            }
            ESP_LOGW(kTag, "[FACE_ENROLL] event=retry code=%s attempt=%d",
                     result.error_code.c_str(), transient_retries);
            vTaskDelay(pdMS_TO_TICKS(400 * transient_retries));
            continue;
        }

        State terminal = State::kFailed;
        if (!HandleUploadError(result, generation, &terminal)) {
            finish_with(terminal);
            return;
        }
    }
}
