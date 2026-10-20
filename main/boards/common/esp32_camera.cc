#include "sdkconfig.h"

#ifdef CONFIG_USE_USB_STREAM

#include <cstring>
#include <cstdlib>
#include <inttypes.h>
#include <stdexcept>
#include <vector>

#include <esp_heap_caps.h>
#include <esp_log.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

#include "usb_stream.h"
#include "board.h"
#include "application.h"
#include "esp32_camera.h"
#include "esp_jpeg_common.h"
#include "esp_jpeg_dec.h"
#include "esp_jpeg_enc.h"
#include "http.h"
#include "identity_client.h"
#include "system_info.h"
#include "task_diagnostics.h"
#include "user_context.h"
#include "vision_credentials.h"

#define TAG "Esp32Camera"

namespace {
constexpr size_t kUvcBufferSize = 88 * 1024;  // Official usb_stream LCD example size.
constexpr uint32_t kCaptureTimeoutMs = 2000;
// USB camera is mounted upside-down and cannot be remounted. Every captured
// JPEG is rotated 180° before face ID / enrollment / VLM upload.
constexpr uint8_t kRotatedJpegQuality = 80;
// Keep the UVC mode within the JPEG buffers used by the application.  This is
// deliberately independent of the LCD resolution: the captured JPEG is sent
// to the application/service, not copied directly to the display.
constexpr uint16_t kUvcMaxWidth = 680;
constexpr uint16_t kUvcMaxHeight = 480;
bool s_first_frame_seen = false;

bool IsHttpsUrl(const std::string& url) {
    return url.size() > 8 && url.compare(0, 8, "https://") == 0;
}



void FlipRgb888180(uint8_t* rgb, uint16_t width, uint16_t height) {
    if (!rgb || width == 0 || height == 0) {
        return;
    }
    const size_t pixels = static_cast<size_t>(width) * static_cast<size_t>(height);
    uint8_t* left = rgb;
    uint8_t* right = rgb + (pixels - 1) * 3;
    while (left < right) {
        const uint8_t tmp0 = left[0];
        const uint8_t tmp1 = left[1];
        const uint8_t tmp2 = left[2];
        left[0] = right[0];
        left[1] = right[1];
        left[2] = right[2];
        right[0] = tmp0;
        right[1] = tmp1;
        right[2] = tmp2;
        left += 3;
        right -= 3;
    }
}

bool RotateJpeg180(CameraJpegBuffer& jpeg) {
    if (jpeg.empty()) {
        return false;
    }

    jpeg_dec_config_t dec_cfg = DEFAULT_JPEG_DEC_CONFIG();
    dec_cfg.output_type = JPEG_PIXEL_FORMAT_RGB888;
    dec_cfg.rotate = JPEG_ROTATE_0D;

    jpeg_dec_handle_t decoder = nullptr;
    task_diag::LogMemoryStage("Esp32Camera", "jpeg_decode_begin");
    jpeg_error_t ret = jpeg_dec_open(&dec_cfg, &decoder);
    if (ret != JPEG_ERR_OK || !decoder) {
        ESP_LOGW(TAG, "[UVC] JPEG decode open failed: %d", static_cast<int>(ret));
        return false;
    }

    jpeg_dec_io_t io = {};
    io.inbuf = jpeg.data();
    io.inbuf_len = static_cast<int>(jpeg.size());
    jpeg_dec_header_info_t info = {};
    ret = jpeg_dec_parse_header(decoder, &io, &info);
    if (ret != JPEG_ERR_OK || info.width == 0 || info.height == 0) {
        jpeg_dec_close(decoder);
        ESP_LOGW(TAG, "[UVC] JPEG header parse failed: %d", static_cast<int>(ret));
        return false;
    }

    int rgb_len = 0;
    ret = jpeg_dec_get_outbuf_len(decoder, &rgb_len);
    if (ret != JPEG_ERR_OK || rgb_len <= 0) {
        rgb_len = static_cast<int>(info.width) * static_cast<int>(info.height) * 3;
    }

    uint8_t* rgb = static_cast<uint8_t*>(heap_caps_aligned_calloc(
        16, 1, static_cast<size_t>(rgb_len), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!rgb) {
        jpeg_dec_close(decoder);
        ESP_LOGW(TAG, "[UVC] JPEG rotate failed: no RGB buffer (%d bytes)", rgb_len);
        return false;
    }
    auto free_rgb = [&]() {
        heap_caps_free(rgb);
        rgb = nullptr;
    };
    io.outbuf = rgb;

    ret = jpeg_dec_process(decoder, &io);
    jpeg_dec_close(decoder);
    task_diag::LogMemoryStage("Esp32Camera", "jpeg_decode_end");
    if (ret != JPEG_ERR_OK) {
        free_rgb();
        ESP_LOGW(TAG, "[UVC] JPEG decode failed: %d", static_cast<int>(ret));
        return false;
    }

    FlipRgb888180(rgb, info.width, info.height);

    jpeg_enc_config_t enc_cfg = DEFAULT_JPEG_ENC_CONFIG();
    enc_cfg.width = info.width;
    enc_cfg.height = info.height;
    enc_cfg.src_type = JPEG_PIXEL_FORMAT_RGB888;
    enc_cfg.subsampling = JPEG_SUBSAMPLE_420;
    enc_cfg.quality = kRotatedJpegQuality;
    enc_cfg.rotate = JPEG_ROTATE_0D;
    enc_cfg.task_enable = false;

    jpeg_enc_handle_t encoder = nullptr;
    task_diag::LogMemoryStage("Esp32Camera", "jpeg_encode_begin");
    ret = jpeg_enc_open(&enc_cfg, &encoder);
    if (ret != JPEG_ERR_OK || !encoder) {
        free_rgb();
        ESP_LOGW(TAG, "[UVC] JPEG encode open failed: %d", static_cast<int>(ret));
        return false;
    }

    size_t out_cap = static_cast<size_t>(info.width) * static_cast<size_t>(info.height) * 3 / 2 + 64 * 1024;
    if (out_cap < 128 * 1024) {
        out_cap = 128 * 1024;
    }
    uint8_t* outbuf = static_cast<uint8_t*>(
        heap_caps_malloc(out_cap, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (!outbuf) {
        jpeg_enc_close(encoder);
        free_rgb();
        ESP_LOGW(TAG, "[UVC] JPEG rotate failed: no encode buffer");
        return false;
    }

    int out_len = 0;
    ret = jpeg_enc_process(encoder, rgb, rgb_len, outbuf, static_cast<int>(out_cap), &out_len);
    jpeg_enc_close(encoder);
    task_diag::LogMemoryStage("Esp32Camera", "jpeg_encode_end");
    free_rgb();
    if (ret != JPEG_ERR_OK || out_len <= 0) {
        heap_caps_free(outbuf);
        ESP_LOGW(TAG, "[UVC] JPEG encode failed: %d", static_cast<int>(ret));
        return false;
    }

    try {
        jpeg.assign(outbuf, outbuf + out_len);
    } catch (const std::bad_alloc&) {
        heap_caps_free(outbuf);
        ESP_LOGE(TAG, "[PHOTO_PSRAM] rotated JPEG copy failed");
        return false;
    }
    heap_caps_free(outbuf);
    return true;
}
}

SemaphoreHandle_t Esp32Camera::frame_sem_ = nullptr;
SemaphoreHandle_t Esp32Camera::frame_lock_ = nullptr;
uint8_t* Esp32Camera::frame_buf_ = nullptr;
size_t Esp32Camera::frame_len_ = 0;
uint16_t Esp32Camera::frame_w_ = 0;
uint16_t Esp32Camera::frame_h_ = 0;
int Esp32Camera::connect_count_ = 0;

void Esp32Camera::UvcFrameCallback(uvc_frame_t* frame, void* user_ptr) {
    auto* self = static_cast<Esp32Camera*>(user_ptr);
    if (!self || !frame || !frame->data || frame->data_bytes == 0 || !frame_buf_ || !frame_lock_) {
        return;
    }
    if (frame->data_bytes > kUvcBufferSize) {
        ESP_LOGW(TAG, "[UVC] Dropped oversized frame: %u bytes (buffer=%u)",
                 static_cast<unsigned>(frame->data_bytes), static_cast<unsigned>(kUvcBufferSize));
        return;
    }

    // The callback is owned by usb_stream.  Never wait here: if a consumer is
    // copying the previous JPEG, the next video frame can safely be dropped.
    if (xSemaphoreTake(frame_lock_, 0) != pdTRUE) {
        return;
    }
    memcpy(frame_buf_, frame->data, frame->data_bytes);
    frame_len_ = frame->data_bytes;
    frame_w_ = frame->width;
    frame_h_ = frame->height;
    xSemaphoreGive(frame_lock_);

    self->streaming_on_ = true;
    self->recovery_.OnFrame();
    if (!s_first_frame_seen) {
        s_first_frame_seen = true;
        ESP_LOGI(TAG, "[UVC] Camera started successfully: first MJPEG frame %ux%u, %u bytes",
                 frame->width, frame->height, static_cast<unsigned>(frame->data_bytes));
    }
    if (frame_sem_) {
        xSemaphoreGive(frame_sem_);
    }
}

void Esp32Camera::UsbStreamStateCallback(usb_stream_state_t event, void* arg) {
    auto* self = static_cast<Esp32Camera*>(arg);
    if (!self) return;

    if (event == STREAM_CONNECTED) {
        ++connect_count_;
        ESP_LOGI(TAG, "[UVC] USB camera connected (session=%d); selecting official usb_stream defaults",
                 connect_count_);

        size_t count = 0;
        esp_err_t err = uvc_frame_size_list_get(nullptr, &count, nullptr);
        if (err != ESP_OK || count == 0) {
            self->streaming_on_ = false;
            ESP_LOGE(TAG, "[UVC] No supported frame size was reported: %s", esp_err_to_name(err));
            return;
        }

        auto* frame_list = static_cast<uvc_frame_size_t*>(malloc(count * sizeof(uvc_frame_size_t)));
        if (!frame_list) {
            self->streaming_on_ = false;
            ESP_LOGE(TAG, "[UVC] Cannot allocate frame-size list");
            return;
        }

        err = uvc_frame_size_list_get(frame_list, nullptr, nullptr);
        if (err != ESP_OK) {
            free(frame_list);
            self->streaming_on_ = false;
            ESP_LOGE(TAG, "[UVC] Cannot read frame-size list: %s", esp_err_to_name(err));
            return;
        }

        // Match the official usb_camera_lcd_display example: retain the
        // descriptor order and use the first mode that fits the UVC policy.
        size_t selected = count;
        for (size_t i = 0; i < count; ++i) {
            const auto& size = frame_list[i];
            ESP_LOGI(TAG, "[UVC] Camera mode[%u]: %ux%u", static_cast<unsigned>(i), size.width, size.height);
            if (size.width <= kUvcMaxWidth && size.height <= kUvcMaxHeight) {
                selected = i;
                break;
            }
        }

        if (selected == count) {
            free(frame_list);
            self->streaming_on_ = false;
            ESP_LOGE(TAG, "[UVC] No camera mode fits the %ux%u UVC buffer policy", kUvcMaxWidth, kUvcMaxHeight);
            return;
        }

        const auto selected_size = frame_list[selected];
        free(frame_list);
        err = uvc_frame_size_reset(selected_size.width, selected_size.height, FPS2INTERVAL(30));
        if (err != ESP_OK) {
            self->streaming_on_ = false;
            ESP_LOGE(TAG, "[UVC] Cannot select %ux%u: %s", selected_size.width, selected_size.height,
                     esp_err_to_name(err));
            return;
        }
        ESP_LOGI(TAG, "[UVC] Selected %ux%u before stream resume", selected_size.width, selected_size.height);

        // Same sequence as Espressif's usb_stream_lcd_display example:
        // enumerate the camera first, then resume the suspended UVC stream.
        err = usb_streaming_control(STREAM_UVC, CTRL_RESUME, nullptr);
        if (err != ESP_OK) {
            self->streaming_on_ = false;
            self->recovery_.OnDisconnected(esp_timer_get_time()/1000);
            ESP_LOGE(TAG, "[UVC] Camera failed to resume: %s", esp_err_to_name(err));
            return;
        }
        self->streaming_on_ = false;
        ESP_LOGI(TAG, "[UVC] Stream resume accepted; waiting for first frame");
    } else if (event == STREAM_DISCONNECTED) {
        self->streaming_on_ = false;
        s_first_frame_seen = false;
        if (frame_sem_) while (xSemaphoreTake(frame_sem_,0)==pdTRUE) {}
        self->recovery_.OnDisconnected(esp_timer_get_time()/1000);
        ESP_LOGW(TAG, "[UVC] USB camera disconnected; capture rejected; bounded recovery scheduled");
    }
}

Esp32Camera::Esp32Camera() {
    ESP_LOGI(TAG, "[UVC] Initializing official usb_stream 1.5.2 MJPEG camera path");
    ESP_LOGI(TAG, "[PHOTO_PSRAM] policy=strict jpeg=psram rgb=psram codec_workspace=psram upload=psram internal_fallback=0");

    s_first_frame_seen = false;
    frame_len_ = 0;
    frame_w_ = 0;
    frame_h_ = 0;

    xfer_buf_a_ = static_cast<uint8_t*>(heap_caps_malloc(kUvcBufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    xfer_buf_b_ = static_cast<uint8_t*>(heap_caps_malloc(kUvcBufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    frame_buffer_ = static_cast<uint8_t*>(heap_caps_malloc(kUvcBufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    frame_buf_ = static_cast<uint8_t*>(heap_caps_malloc(kUvcBufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    frame_sem_ = xSemaphoreCreateBinary();
    frame_lock_ = xSemaphoreCreateMutex();

    auto cleanup = [this]() {
        if (usb_started_) {
            usb_streaming_stop();
            usb_started_ = false;
        }
        if (frame_lock_) { vSemaphoreDelete(frame_lock_); frame_lock_ = nullptr; }
        if (frame_sem_) { vSemaphoreDelete(frame_sem_); frame_sem_ = nullptr; }
        if (frame_buf_) { heap_caps_free(frame_buf_); frame_buf_ = nullptr; }
        if (frame_buffer_) { heap_caps_free(frame_buffer_); frame_buffer_ = nullptr; }
        if (xfer_buf_b_) { heap_caps_free(xfer_buf_b_); xfer_buf_b_ = nullptr; }
        if (xfer_buf_a_) { heap_caps_free(xfer_buf_a_); xfer_buf_a_ = nullptr; }
        frame_len_ = 0;
        streaming_on_ = false;
    };

    if (!xfer_buf_a_ || !xfer_buf_b_ || !frame_buffer_ || !frame_buf_ || !frame_sem_ || !frame_lock_) {
        ESP_LOGE(TAG, "[UVC] Initialization failed: PSRAM buffer or synchronization allocation failed");
        cleanup();
        return;
    }

    esp_err_t err=StartUsbHost();
    if (err!=ESP_OK) {
        ESP_LOGE(TAG,"[UVC] USB host start failed: %s",esp_err_to_name(err));
        cleanup();return;
    }
    usb_started_ = true;
    recovery_done_=false;
    TaskHandle_t recovery_task=nullptr;
    if (xTaskCreateWithCaps(RecoveryWorker,"usb_cam_recover",4096,this,2,&recovery_task,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)!=pdPASS) {
        recovery_done_=true;
        ESP_LOGE(TAG,"[UVC] recovery worker unavailable: resource_exhausted");
    }

    // usb_stream performs enumeration in its own tasks.  Keep those tasks and
    // the Host controller alive even when no camera is currently attached.
    // This mirrors the official example's lifetime without blocking the rest
    // of the board startup in usb_streaming_connect_wait(portMAX_DELAY).
    ESP_LOGI(TAG, "[UVC] USB Host is running persistently; waiting for camera connection");
}

esp_err_t Esp32Camera::StartUsbHost() {
    // Do not hard-code endpoint, interface, format index, or resolution.  The
    // driver parses the descriptors supplied by the newly selected UVC camera.
    uvc_config_t config = {
        .frame_width = FRAME_RESOLUTION_ANY,
        .frame_height = FRAME_RESOLUTION_ANY,
        .frame_interval = FRAME_INTERVAL_FPS_30,
        .xfer_buffer_size = kUvcBufferSize,
        .xfer_buffer_a = xfer_buf_a_,
        .xfer_buffer_b = xfer_buf_b_,
        .frame_buffer_size = kUvcBufferSize,
        .frame_buffer = frame_buffer_,
        .frame_cb = UvcFrameCallback,
        .frame_cb_arg = this,
        .format = UVC_FORMAT_MJPEG,
        .flags = FLAG_UVC_SUSPEND_AFTER_START,
    };

    esp_err_t err=uvc_streaming_config(&config);
    if (err!=ESP_OK)return err;
    err=usb_streaming_state_register(&UsbStreamStateCallback,this);
    if (err!=ESP_OK)return err;
    return usb_streaming_start();
}

void Esp32Camera::RecoveryWorker(void* arg) {
    auto* self=static_cast<Esp32Camera*>(arg);
    while (!self->recovery_stop_.load()) {
        const auto action=self->recovery_.Poll(esp_timer_get_time()/1000);
        if (action==UsbCameraRecovery::Action::kStop) {
            self->streaming_on_=false;
            const esp_err_t result=self->usb_started_?usb_streaming_stop():ESP_OK;
            if (result==ESP_OK)self->usb_started_=false;
            self->streaming_on_=false;
            self->recovery_.Stopped(result==ESP_OK,esp_timer_get_time()/1000);
            ESP_LOGW(TAG,"[UVC] recovery phase=stop result=%s",esp_err_to_name(result));
        } else if (action==UsbCameraRecovery::Action::kStart) {
            const esp_err_t result=self->StartUsbHost();
            if (result==ESP_OK)self->usb_started_=true;
            self->recovery_.Started(result==ESP_OK,esp_timer_get_time()/1000);
            ESP_LOGW(TAG,"[UVC] recovery phase=reenumerate result=%s",esp_err_to_name(result));
        }
        vTaskDelay(pdMS_TO_TICKS(250));
    }
    self->recovery_done_=true;
    vTaskDeleteWithCaps(nullptr);
}

Esp32Camera::~Esp32Camera() {
    ESP_LOGI(TAG, "[UVC] Stopping USB camera stream");
    recovery_.Close();recovery_stop_=true;
    while (!recovery_done_.load())vTaskDelay(pdMS_TO_TICKS(10));
    streaming_on_ = false;
    if (usb_started_) {
        usb_streaming_stop();
        usb_started_ = false;
    }
    if (frame_lock_) { vSemaphoreDelete(frame_lock_); frame_lock_ = nullptr; }
    if (frame_sem_) { vSemaphoreDelete(frame_sem_); frame_sem_ = nullptr; }
    if (frame_buf_) { heap_caps_free(frame_buf_); frame_buf_ = nullptr; }
    if (frame_buffer_) { heap_caps_free(frame_buffer_); frame_buffer_ = nullptr; }
    if (xfer_buf_b_) { heap_caps_free(xfer_buf_b_); xfer_buf_b_ = nullptr; }
    if (xfer_buf_a_) { heap_caps_free(xfer_buf_a_); xfer_buf_a_ = nullptr; }
    frame_len_ = 0;
}

bool Esp32Camera::Capture() {
    if (!streaming_on_.load(std::memory_order_acquire) || !frame_sem_ || !frame_lock_) {
        ESP_LOGW(TAG, "[UVC] Capture rejected: camera stream is not ready");
        return false;
    }
    ESP_LOGI(TAG, "[UVC] Capture requested; waiting for the next camera frame");
    if (xSemaphoreTake(frame_sem_, pdMS_TO_TICKS(kCaptureTimeoutMs)) != pdTRUE) {
        ESP_LOGW(TAG, "[UVC] Capture failed: no frame in %ums", kCaptureTimeoutMs);
        return false;
    }
    if (xSemaphoreTake(frame_lock_, pdMS_TO_TICKS(kCaptureTimeoutMs)) != pdTRUE) {
        ESP_LOGW(TAG, "[UVC] Capture failed: frame buffer remained busy");
        return false;
    }
    if (!streaming_on_.load() || frame_len_ == 0 || !frame_buf_) {
        xSemaphoreGive(frame_lock_);
        ESP_LOGW(TAG, "[UVC] Capture failed: received an empty frame");
        return false;
    }
    CameraJpegBuffer jpeg;
    try {
        jpeg.assign(frame_buf_, frame_buf_ + frame_len_);
    } catch (const std::bad_alloc&) {
        xSemaphoreGive(frame_lock_);
        ESP_LOGE(TAG, "[PHOTO_PSRAM] capture copy failed; frame lock released");
        return false;
    }
    const uint16_t width = frame_w_;
    const uint16_t height = frame_h_;
    xSemaphoreGive(frame_lock_);

    const int64_t rotate_start_us = esp_timer_get_time();
    const size_t src_bytes = jpeg.size();
    bool orientation_trusted = true;
    if (!RotateJpeg180(jpeg)) {
        orientation_trusted = false;
        ESP_LOGW(TAG,
                 "[UVC] 180° rotate failed; enrollment must not upload this "
                 "frame (orientation untrusted)");
    } else {
        ESP_LOGI(TAG, "[UVC] Rotated capture 180° in %d ms (%u -> %u bytes)",
                 static_cast<int>((esp_timer_get_time() - rotate_start_us) / 1000),
                 static_cast<unsigned>(src_bytes),
                 static_cast<unsigned>(jpeg.size()));
    }

    const size_t out_bytes = jpeg.size();
    {
        std::lock_guard<std::mutex> lock(state_mutex_);
        last_jpeg_ = std::move(jpeg);
        last_jpeg_orientation_trusted_ = orientation_trusted;
    }
    frame_.width = width;
    frame_.height = height;
    ESP_LOGI(TAG, "[UVC] Capture succeeded: %ux%u, %u bytes trusted=%d",
             frame_.width, frame_.height, static_cast<unsigned>(out_bytes),
             orientation_trusted ? 1 : 0);
    return true;
}

bool Esp32Camera::SetHMirror(bool) { return false; }
bool Esp32Camera::SetVFlip(bool) { return false; }
CameraJpegBuffer Esp32Camera::GetLastJpeg() {
    std::lock_guard<std::mutex> lock(state_mutex_);
    try {
        return last_jpeg_;
    } catch (const std::bad_alloc&) {
        ESP_LOGE(TAG, "[PHOTO_PSRAM] last JPEG copy failed");
        return {};
    }
}

bool Esp32Camera::LastJpegOrientationTrusted() const {
    std::lock_guard<std::mutex> lock(state_mutex_);
    return last_jpeg_orientation_trusted_;
}

void Esp32Camera::SetExplainUrl(const std::string& url, const std::string& token) {
    std::lock_guard<std::mutex> lock(state_mutex_);
    explain_url_ = url;
    explain_token_ = token;
}

void Esp32Camera::SetSessionId(const std::string& session_id) {
    std::lock_guard<std::mutex> lock(state_mutex_);
    session_id_ = session_id;
}

std::string Esp32Camera::Explain(const std::string& question) {
    CameraJpegBuffer jpeg;
    {
        std::lock_guard<std::mutex> lock(state_mutex_);
        jpeg = last_jpeg_;
    }
    return Explain(question, jpeg);
}

std::string Esp32Camera::Explain(const std::string& question,
                                 const CameraJpegBuffer& jpeg) {
    VisionCredentialSnapshot snap;
    if (!VisionCredentialStore::GetInstance().TryAcquireExplainSnapshot(&snap)) {
        throw std::runtime_error("vision_not_ready: 视觉服务尚未就绪，请稍后再试");
    }
    if (!IsHttpsUrl(snap.explain_url)) {
        throw std::runtime_error("Vision service must use an HTTPS URL");
    }
    if (jpeg.empty()) throw std::runtime_error("No frame captured yet");
    auto http = Board::GetInstance().GetNetwork()->CreateHttp(3);
    if (!http) throw std::runtime_error("Failed to create HTTP client");
    std::string boundary = "----ESP32_CAMERA_BOUNDARY";
    http->SetHeader("Device-Id", SystemInfo::GetMacAddress().c_str());
    http->SetHeader("Client-Id", Board::GetInstance().GetUuid().c_str());
    if (!snap.session_id.empty()) {
        http->SetHeader("Session-Id", snap.session_id.c_str());
    }
    if (!snap.token.empty()) {
        http->SetHeader("Authorization", ("Bearer " + snap.token).c_str());
    }
    http->SetHeader("Content-Type", ("multipart/form-data; boundary=" + boundary).c_str());
    std::string q = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"question\"\r\n\r\n" + question + "\r\n";
    std::string h = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"camera.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n";
    std::string footer = "\r\n--" + boundary + "--\r\n";
    CameraMultipartBody body;
    body.reserve(q.size() + h.size() + jpeg.size() + footer.size());
    body.append(q);
    body.append(h);
    body.append(reinterpret_cast<const char*>(jpeg.data()), jpeg.size());
    body.append(footer);
    http->SetPsramContent(std::move(body));
    ESP_LOGI(TAG,
             "event=explain_upload generation=%u session_len=%u",
             static_cast<unsigned>(snap.connection_generation),
             static_cast<unsigned>(snap.session_id.size()));
    if (!http->Open("POST", snap.explain_url)) {
        throw std::runtime_error("Failed to connect to explain URL");
    }
    const int status = http->GetStatusCode();
    if (status != 200) {
        bool truncated = false;
        std::string err_body = ReadHttpBodyBounded(http.get(), 512, &truncated);
        if (!truncated) {
            http->Close();
        }
        ESP_LOGW(TAG,
                 "event=explain_http_error status=%d generation=%u body_len=%u "
                 "truncated=%d",
                 status,
                 static_cast<unsigned>(snap.connection_generation),
                 static_cast<unsigned>(err_body.size()),
                 truncated ? 1 : 0);
        throw std::runtime_error("vision_http_" + std::to_string(status) +
                                 ": 识物服务返回 HTTP " + std::to_string(status));
    }
    std::string result = http->ReadAll();
    http->Close();
    return result;
}

IdentityResult Esp32Camera::IdentifyFace(
    const CameraJpegBuffer& jpeg_data) {
    return IdentifyFace(jpeg_data, 0);
}

IdentityResult Esp32Camera::IdentifyFace(
    const CameraJpegBuffer& jpeg_data, uint32_t request_generation) {
    // Prefer MCP-issued short-lived identity_url; never use long-lived FACE_API_* secrets.
    IdentityResult result =
        IdentityClient::GetInstance().IdentifyJpeg(jpeg_data,
                                                   request_generation);
    if (result.status.empty()) result.status = "error";
    // Identification is observational. Callers that own an identity flow
    // decide separately whether a confirmed result should update presence;
    // MCP who-am-I must never change the voice-authenticated current user.
    return result;
}

void Esp32Camera::IdentifyFace(const CameraJpegBuffer& jpeg_data,
                               std::string& out_status,
                               std::string& out_name) {
    IdentityResult result = IdentifyFace(jpeg_data);
    out_status = result.status.empty() ? "error" : result.status;
    out_name.clear();
    if (!result.display_name.empty()) {
        out_name = result.display_name;
    } else if (result.IsKnownPerson()) {
        // Never treat display_name as authentication; use the stable user ID
        // only as a fallback label.
        out_name = result.user_id;
    }
}

#endif // CONFIG_USE_USB_STREAM
