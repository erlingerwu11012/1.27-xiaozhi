#pragma once
#include "camera_image_buffer.h"
#include "sdkconfig.h"

#ifndef CONFIG_IDF_TARGET_ESP32
#include <thread>
#include <memory>
#include <mutex>
#include <atomic>
#include <vector>

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>

#include "camera.h"
#include "identity_client.h"
#ifndef CONFIG_USE_USB_STREAM
#include <linux/videodev2.h>
using v4l2_pix_fmt_t = uint32_t;
#endif

#ifdef CONFIG_USE_USB_STREAM
#include "usb_stream.h"
#else
#include "esp_video_init.h"
#endif

struct JpegChunk {
    uint8_t* data;
    size_t len;
};

#ifdef CONFIG_USE_USB_STREAM
#include "usb_camera_recovery.h"
#endif

class Esp32Camera : public Camera {
private:
    struct FrameBuffer {
        uint8_t *data = nullptr;
        size_t len = 0;
        uint16_t width = 0;
        uint16_t height = 0;
#ifndef CONFIG_USE_USB_STREAM
        v4l2_pix_fmt_t format = 0;
#endif
    } frame_;

#ifdef CONFIG_USE_USB_STREAM
    static SemaphoreHandle_t frame_sem_;
    static uint8_t* frame_buf_;
    static size_t frame_len_;
    static uint16_t frame_w_;
    static uint16_t frame_h_;
    static int connect_count_;
    static SemaphoreHandle_t frame_lock_;
    std::atomic<bool> streaming_on_{false};
    std::atomic<bool> usb_started_{false};
    std::atomic<bool> recovery_stop_{false};
    std::atomic<bool> recovery_done_{true};
    UsbCameraRecovery recovery_;
    esp_err_t StartUsbHost();
    static void RecoveryWorker(void* arg);
    uint8_t* xfer_buf_a_ = nullptr;
    uint8_t* xfer_buf_b_ = nullptr;
    uint8_t* frame_buffer_ = nullptr;
#else
    v4l2_pix_fmt_t sensor_format_ = 0;
#ifdef CONFIG_XIAOZHI_ENABLE_ROTATE_CAMERA_IMAGE
    uint16_t sensor_width_ = 0;
    uint16_t sensor_height_ = 0;
#endif
    int video_fd_ = -1;
    bool streaming_on_ = false;
    struct MmapBuffer { void *start = nullptr; size_t length = 0; };
    std::vector<MmapBuffer> mmap_buffers_;
#endif

    std::string explain_url_;
    std::string explain_token_;
    std::string session_id_;
    mutable std::mutex state_mutex_;
    std::thread encoder_thread_;
    CameraJpegBuffer last_jpeg_;
    bool last_jpeg_orientation_trusted_ = true;

#ifdef CONFIG_USE_USB_STREAM
    static void UvcFrameCallback(uvc_frame_t* frame, void* user_ptr);
    static void UsbStreamStateCallback(usb_stream_state_t event, void* arg);
#endif

public:
#ifdef CONFIG_USE_USB_STREAM
    Esp32Camera();
#else
    Esp32Camera(const esp_video_init_config_t& config, bool skip_init = false);
#endif
    ~Esp32Camera();

    virtual void SetExplainUrl(const std::string& url, const std::string& token);
    void SetSessionId(const std::string& session_id);
    virtual bool Capture();
    virtual bool SetHMirror(bool enabled) override;
    virtual bool SetVFlip(bool enabled) override;
    virtual std::string Explain(const std::string& question);
    virtual std::string Explain(const std::string& question,
                                const CameraJpegBuffer& jpeg) override;

#ifdef CONFIG_USE_USB_STREAM
    bool IsInvalid() const { return !usb_started_; }
    bool IsStreamReady() const { return streaming_on_.load(std::memory_order_acquire); }
#else
    bool IsInvalid() const { return video_fd_ < 0; }
#endif

    CameraJpegBuffer GetLastJpeg();
    // True when the last Capture() produced an upright JPEG suitable for
    // enrollment direction guidance.  False if 180° rotate failed (frame may
    // still be in last_jpeg_ for non-enrollment callers).
    bool LastJpegOrientationTrusted() const;

    // Returns IdentityResult with usr_* user_id when known.
    // display_name is for UI/greeting only and must not authorize.
    IdentityResult IdentifyFace(const CameraJpegBuffer& jpeg_data);
    IdentityResult IdentifyFace(const CameraJpegBuffer& jpeg_data,
                                uint32_t request_generation);

    // Compatibility wrapper: status + display_name (not an auth key).
    void IdentifyFace(const CameraJpegBuffer& jpeg_data,
                      std::string& out_status,
                      std::string& out_name);
};

#endif // ndef CONFIG_IDF_TARGET_ESP32
