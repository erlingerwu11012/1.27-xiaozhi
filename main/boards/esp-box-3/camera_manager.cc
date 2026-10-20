#include "camera_manager.h"
#include "config.h"
#include "esp32_camera.h"
#include "task_diagnostics.h"
#include "board.h"
#include "display.h"

#include <esp_log.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <esp_heap_caps.h>

#ifndef CONFIG_USE_USB_STREAM
#if CONFIG_ESP_VIDEO_ENABLE_USB_UVC_VIDEO_DEVICE
#include <esp_video_init.h>
#endif
#endif


#define TAG "CameraManager"

bool CameraManager::video_init_done_ = false;

CameraManager& CameraManager::GetInstance() {
    static CameraManager instance;
    return instance;
}

bool CameraManager::IsStreamReady() {
#ifdef CONFIG_USE_USB_STREAM
    auto* camera = persistent_camera_;
    const bool ready = camera != nullptr && !camera->IsInvalid() && camera->IsStreamReady();
    if (ready) {
        stream_state_.store(StreamState::Ready, std::memory_order_release);
    } else if (camera != nullptr && !camera->IsInvalid()) {
        stream_state_.store(StreamState::Opening, std::memory_order_release);
    }
    return ready;
#else
    return stream_state_.load(std::memory_order_acquire) == StreamState::Ready;
#endif
}

bool CameraManager::IsUvcDeviceConnected() {
#ifdef CONFIG_USE_USB_STREAM
    return IsStreamReady() && persistent_camera_ != nullptr && !persistent_camera_->IsInvalid();
#else
#if CONFIG_ESP_VIDEO_ENABLE_USB_UVC_VIDEO_DEVICE
    return esp_video_uvc_is_device_connected();
#else
    return true;
#endif
#endif
}

bool CameraManager::WaitForUvcReady(int timeout_ms, int poll_interval_ms) {
    const int64_t deadline_us = esp_timer_get_time() + static_cast<int64_t>(timeout_ms) * 1000;
    while (esp_timer_get_time() < deadline_us) {
        if (IsStreamReady()) {
            return true;
        }
        vTaskDelay(pdMS_TO_TICKS(poll_interval_ms));
    }
    return IsStreamReady();
}

void CameraManager::PowerCycle() {
}

bool CameraManager::OpenPersistentStream() {
    if (IsStreamReady()) {
        ESP_LOGW(TAG, "OpenPersistentStream: already open");
        return true;
    }

#ifdef CONFIG_USE_USB_STREAM
    if (persistent_camera_ != nullptr && !persistent_camera_->IsInvalid()) {
        stream_state_.store(StreamState::Opening, std::memory_order_release);
        ESP_LOGI(TAG, "OpenPersistentStream: USB Host already running; still waiting for UVC device");
        return true;
    }
#endif

    // 尝试获取初始化锁（非阻塞：若已有其他路径在初始化则直接跳过）
    if (!open_mutex_.try_lock()) {
        ESP_LOGW(TAG, "OpenPersistentStream: BLOCKED by concurrent init, skip");
        return false;
    }
    // RAII 解锁
    struct LockGuard {
        std::mutex& m;
        ~LockGuard() { m.unlock(); }
    } lg{open_mutex_};

    if (IsStreamReady()) {
        ESP_LOGW(TAG, "OpenPersistentStream: already open (post-lock check)");
        return true;
    }

    stream_state_.store(StreamState::Opening, std::memory_order_release);

#ifdef CONFIG_USE_USB_STREAM
    size_t free_dma = heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA);
    size_t block_dma = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA);
    ESP_LOGI(TAG, "OpenPersistentStream: opening usb_stream camera (dma_free=%u largest=%u)",
             (unsigned)free_dma, (unsigned)block_dma);
    persistent_camera_ = new Esp32Camera();
#else
    esp_video_init_config_t uvc_cfg = {};
#if CONFIG_ESP_VIDEO_ENABLE_USB_UVC_VIDEO_DEVICE
    static esp_video_init_usb_uvc_config_t uvc_dev_cfg = {};
    uvc_dev_cfg.usb.init_usb_host_lib = true;
    uvc_dev_cfg.uvc.uvc_dev_num       = 1;
    uvc_cfg.usb_uvc = &uvc_dev_cfg;
#endif
    persistent_camera_ = new Esp32Camera(uvc_cfg, true);
#endif

    if (!persistent_camera_ || persistent_camera_->IsInvalid()) {
        ESP_LOGE(TAG, "OpenPersistentStream: open failed");
        delete persistent_camera_;
        persistent_camera_ = nullptr;
        stream_state_.store(StreamState::Failed, std::memory_order_release);
        return false;
    }

    {
        std::lock_guard<std::mutex> session_lock(session_mutex_);
        if (!session_id_.empty()) persistent_camera_->SetSessionId(session_id_);
        if (!explain_url_.empty()) {
            persistent_camera_->SetExplainUrl(explain_url_, explain_token_);
        }
    }

#ifdef CONFIG_USE_USB_STREAM
    if (persistent_camera_->IsStreamReady()) {
        stream_state_.store(StreamState::Ready, std::memory_order_release);
        ESP_LOGI(TAG, "OpenPersistentStream: UVC stream ready");
    } else {
        stream_state_.store(StreamState::Opening, std::memory_order_release);
        ESP_LOGI(TAG, "OpenPersistentStream: USB Host started; UVC device may connect later");
    }
#else
    stream_state_.store(StreamState::Ready, std::memory_order_release);
    ESP_LOGI(TAG, "OpenPersistentStream: stream open OK");
#endif
    return true;
}

bool CameraManager::TryAcquire(bool background) {
    hardware_failed_ = false;

    if (!IsStreamReady()) {
        ESP_LOGW(TAG, "TryAcquire: stream is not ready (state=%d)",
                 static_cast<int>(GetStreamState()));
        return false;
    }

    if (!mutex_.try_lock()) {
        ESP_LOGW(TAG, "Camera busy, TryAcquire failed");
        return false;
    }

    if (!persistent_camera_ || persistent_camera_->IsInvalid()) {
        ESP_LOGE(TAG, "TryAcquire: persistent stream not available");
        hardware_failed_ = true;
        mutex_.unlock();
        return false;
    }

    camera_ = persistent_camera_;
    foreground_operation_active_.store(!background);
    operation_active_.store(true);
    if (!background) {
        if (auto* display = Board::GetInstance().GetDisplay())
            display->WakeFromStandbyClock();
    }
    ESP_LOGI(TAG, "TryAcquire: camera acquired OK (persistent stream)");
    return true;
}

bool CameraManager::AcquireWithRetry(int max_retries, bool background) {
    if (!IsStreamReady()) {
        ESP_LOGW(TAG, "AcquireWithRetry: UVC startup owns initialization (state=%d); defer request",
                 static_cast<int>(GetStreamState()));
        hardware_failed_ = false;
        return false;
    }

    for (int attempt = 0; attempt <= max_retries; attempt++) {
        if (attempt > 0) {
            if (!hardware_failed_) return false;
            ESP_LOGW(TAG, "AcquireWithRetry: retry %d/%d", attempt, max_retries);
            vTaskDelay(pdMS_TO_TICKS(500));
        }
        if (TryAcquire(background)) return true;
    }
    ESP_LOGE(TAG, "AcquireWithRetry: all %d attempts failed", max_retries + 1);
    return false;
}

void CameraManager::Release() {
    camera_ = nullptr;
    operation_active_.store(false);
    foreground_operation_active_.store(false);
    mutex_.unlock();
}

void CameraManager::EnsurePowerOff() {
}

Camera* CameraManager::GetCamera() {
    return camera_;
}

// =============================================================================
// 模式二：常开预览 + 存在状态机
// =============================================================================

// Live camera preview is intentionally excluded from this firmware build.
// Public compatibility stubs reject preview requests. One-shot Capture()
// remains available.

bool CameraManager::StartPreview(
    std::function<void(const std::string& name)> on_face_cb,
    std::function<void(PresenceState)> on_ui_cb,
    std::function<void(uint32_t, const CameraJpegBuffer&)> on_frame_cb) {
    (void)on_face_cb;
    (void)on_ui_cb;
    (void)on_frame_cb;
    ESP_LOGW(TAG, "Live camera preview is disabled");
    return false;
}

bool CameraManager::StopPreview() {
    return true;
}

bool CameraManager::IsPreviewActive() const {
    return false;
}

bool CameraManager::IsPreviewSessionActive(uint32_t session_id) const {
    (void)session_id;
    return false;
}

void CameraManager::SetSessionId(const std::string& session_id) {
    std::lock_guard<std::mutex> session_lock(session_mutex_);
    session_id_ = session_id;
    if (persistent_camera_) persistent_camera_->SetSessionId(session_id_);
}

void CameraManager::SetExplainUrl(const std::string& url, const std::string& token) {
    std::lock_guard<std::mutex> session_lock(session_mutex_);
    explain_url_ = url;
    explain_token_ = token;
    if (persistent_camera_) {
        persistent_camera_->SetExplainUrl(explain_url_, explain_token_);
    }
}


CameraJpegBuffer CameraManager::GetLastFrame() {
    return {};
}

CameraManager::PresenceState CameraManager::GetPresenceState() const {
    return PresenceState::EMPTY;
}

void CameraManager::SetEngaged(bool engaged) {
    (void)engaged;
}
