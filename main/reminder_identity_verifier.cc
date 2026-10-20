#include "reminder_identity_verifier.h"

#include "boards/esp-box-3/camera_manager.h"
#include "boards/common/esp32_camera.h"
#include "presence_context.h"
#include "task_diagnostics.h"

#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

namespace {
constexpr const char* kTag = "ReminderIdVerify";
}

ReminderIdentityVerifier& ReminderIdentityVerifier::GetInstance() {
    static ReminderIdentityVerifier instance;
    return instance;
}

void ReminderIdentityVerifier::Start() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (started_) return;
    started_ = true;
    TaskHandle_t handle = nullptr;
    xTaskCreate(WorkerEntry, "rem_id_verify", 8192, this, 3, &handle);
    worker_handle_ = handle;
    task_diag::LogTaskHandle(kTag, "rem_id_verify_created", handle, 3, -1);
}

bool ReminderIdentityVerifier::IsBusy() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return busy_ || has_pending_;
}

bool ReminderIdentityVerifier::RequestVerification(
    const ReminderIdentityRequest& request, Callback callback) {
    if (!PresenceContext::IsUsrPersonId(request.recipient_person_id)) {
        return false;
    }
    Start();
    std::lock_guard<std::mutex> lock(mutex_);
    if (busy_ || has_pending_) {
        ESP_LOGI(kTag,
                 "[REMINDER_DELIVERY] event=camera_busy instance=%s",
                 request.instance_id.c_str());
        return false;
    }
    pending_ = request;
    pending_callback_ = std::move(callback);
    has_pending_ = true;
    ESP_LOGI(kTag,
             "[REMINDER_DELIVERY] event=verify_start instance=%s rev=%u "
             "recipient=%s gen=%u",
             request.instance_id.c_str(),
             static_cast<unsigned>(request.revision),
             request.recipient_person_id.c_str(),
             static_cast<unsigned>(request.presence_generation));
    return true;
}

void ReminderIdentityVerifier::WorkerEntry(void* arg) {
    static_cast<ReminderIdentityVerifier*>(arg)->WorkerLoop();
}

void ReminderIdentityVerifier::WorkerLoop() {
    task_diag::LogCurrentTask(kTag, "rem_id_verify_start", 3, -1);
    while (true) {
        ReminderIdentityRequest request;
        Callback callback;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!has_pending_) {
                // fall through to delay
            } else {
                request = pending_;
                callback = std::move(pending_callback_);
                has_pending_ = false;
                busy_ = true;
            }
        }
        if (!callback) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }

        ReminderIdentityOutcome outcome = RunVerification(request);
        {
            std::lock_guard<std::mutex> lock(mutex_);
            busy_ = false;
        }
        if (callback) {
            callback(outcome);
        }
    }
}

ReminderIdentityOutcome ReminderIdentityVerifier::RunVerification(
    const ReminderIdentityRequest& request) {
    ReminderIdentityOutcome outcome;
    outcome.request = request;
    outcome.confirmed = false;

    auto& presence = PresenceContext::GetInstance();
    if (!presence.IsRadarPresent() ||
        presence.PresenceGeneration() != request.presence_generation) {
        outcome.reason = "absence";
        return outcome;
    }
    if (!IdentityClient::GetInstance().HasIdentityEndpoint()) {
        outcome.reason = "vision_not_ready";
        return outcome;
    }

    auto& cam_mgr = CameraManager::GetInstance();
    if (cam_mgr.IsPreviewActive()) {
        outcome.reason = "camera_busy";
        return outcome;
    }
    if (!cam_mgr.IsStreamReady()) {
        outcome.reason = "camera_not_ready";
        return outcome;
    }
    if (!cam_mgr.TryAcquire()) {
        outcome.reason = "camera_busy";
        return outcome;
    }

    struct ReleaseGuard {
        CameraManager& manager;
        ~ReleaseGuard() { manager.Release(); }
    } guard{cam_mgr};

    auto* camera = static_cast<Esp32Camera*>(cam_mgr.GetCamera());
    if (!camera) {
        outcome.reason = "error";
        return outcome;
    }

    auto capture_once = [&](IdentityResult& out) -> bool {
        if (!presence.IsRadarPresent() ||
            presence.PresenceGeneration() != request.presence_generation) {
            outcome.reason = "absence";
            return false;
        }
        if (!camera->Capture()) {
            outcome.reason = "error";
            out.status = "error";
            out.error_reason = "capture_failed";
            return false;
        }
        out = IdentityClient::GetInstance().IdentifyJpeg(
            camera->GetLastJpeg(), request.presence_generation);
        return true;
    };

    if (!capture_once(outcome.first)) {
        if (outcome.reason.empty()) outcome.reason = "error";
        return outcome;
    }
    if (!outcome.first.IsKnownPerson()) {
        outcome.reason = outcome.first.status.empty()
                             ? "error"
                             : outcome.first.status;
        return outcome;
    }
    if (outcome.first.user_id != request.recipient_person_id) {
        outcome.reason = "wrong_person";
        return outcome;
    }

    vTaskDelay(pdMS_TO_TICKS(120));

    if (!capture_once(outcome.second)) {
        if (outcome.reason.empty()) outcome.reason = "error";
        return outcome;
    }
    if (!outcome.second.IsKnownPerson()) {
        outcome.reason = outcome.second.status.empty()
                             ? "error"
                             : outcome.second.status;
        return outcome;
    }
    if (outcome.second.user_id != outcome.first.user_id) {
        outcome.reason = "inconsistent";
        return outcome;
    }
    if (outcome.second.user_id != request.recipient_person_id) {
        outcome.reason = "wrong_person";
        return outcome;
    }

    if (!presence.IsRadarPresent() ||
        presence.PresenceGeneration() != request.presence_generation) {
        outcome.reason = "stale";
        return outcome;
    }

    presence.SetConfirmedIdentity(
        outcome.second.user_id, outcome.second.display_name,
        outcome.second.confidence, outcome.second.status,
        request.presence_generation);
    outcome.confirmed = true;
    outcome.reason = "confirmed";
    return outcome;
}
