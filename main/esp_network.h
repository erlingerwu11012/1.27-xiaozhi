#pragma once
#include "network_interface.h"
#include "task_diagnostics.h"

#include <string>
#include <functional>
#include <memory>
#include <vector>
#include <climits>

#include <esp_http_client.h>
#include <esp_websocket_client.h>
#include <esp_transport_ws.h>
#include <mqtt_client.h>
#include <lwip/sockets.h>
#include <lwip/netdb.h>
#include <esp_log.h>
#include <esp_crt_bundle.h>
#include <esp_timer.h>
#include <cerrno>
#include <cstring>

#include "ota_tls_diag.h"
#include <esp_wifi.h>
#include <esp_netif.h>
#include <esp_heap_caps.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

// ─── Http 实现 ────────────────────────────────────────────────────────────────

class EspHttp : public Http {
public:
    EspHttp() = default;
    ~EspHttp() override { Close(); }

    void SetHeader(const char* key, const char* value) override {
        headers_.push_back({key, value});
    }

    void SetContent(std::string&& content) override {
        CameraMultipartBody{}.swap(photo_content_);
        photo_content_active_ = false;
        content_ = std::move(content);
    }

    void SetPsramContent(CameraMultipartBody&& content) override {
        std::string{}.swap(content_);
        photo_content_ = std::move(content);
        photo_content_active_ = true;
    }

    bool Open(const char* method, const std::string& url) override {
        Close();
        diag_attempt_id_ = OtaTlsDiag::ActiveAttemptId();

        esp_http_client_config_t config = {};
        config.url = url.c_str();
        config.method = HTTP_METHOD_GET;
        if (strcmp(method, "POST") == 0) {
            config.method = HTTP_METHOD_POST;
        } else if (strcmp(method, "PUT") == 0) {
            config.method = HTTP_METHOD_PUT;
        } else if (strcmp(method, "DELETE") == 0) {
            config.method = HTTP_METHOD_DELETE;
        }
        config.buffer_size = 4096;
        config.buffer_size_tx = 4096;
        config.timeout_ms = 30000;
        config.crt_bundle_attach = esp_crt_bundle_attach;
        config.event_handler = &EspHttp::HttpEventHandler;
        config.user_data = this;

        last_esp_tls_err_ = ESP_OK;
        last_mbedtls_err_ = 0;
        last_tls_flags_ = 0;
        last_errno_ = 0;
        last_open_err_ = ESP_OK;

        client_ = esp_http_client_init(&config);
        if (!client_) {
            return false;
        }

        for (auto& h : headers_) {
            esp_http_client_set_header(client_, h.first.c_str(), h.second.c_str());
        }

        // Single POST/PUT body path: open(content_length) then exactly one full write.
        // Do NOT call set_post_field here; that API is for esp_http_client_perform only.
        const size_t body_size = photo_content_active_ ? photo_content_.size() : content_.size();
        if (body_size > static_cast<size_t>(INT_MAX)) {
            Close();
            return false;
        }
        const char* body_data = photo_content_active_ ? photo_content_.data() : content_.data();
        const int write_len = static_cast<int>(body_size);
        OtaTlsDiag::LogStage(diag_attempt_id_, "http_open_begin");
        OtaTlsDiag::LogHeapWifi(diag_attempt_id_, "http_open_begin");

        esp_err_t err = esp_http_client_open(client_, write_len);
        last_open_err_ = err;
        if (err != ESP_OK) {
            CaptureTlsErrorFromClient();
            OtaTlsDiag::LogTlsError(diag_attempt_id_, err, last_esp_tls_err_, last_mbedtls_err_,
                                    last_tls_flags_, last_errno_);
            OtaTlsDiag::LogStage(diag_attempt_id_, "http_open_fail");
            OtaTlsDiag::LogClose(diag_attempt_id_, "open_fail_cleanup");
            esp_http_client_close(client_);
            esp_http_client_cleanup(client_);
            client_ = nullptr;
            return false;
        }

        if (write_len > 0) {
            int written = 0;
            while (written < write_len) {
                int n = esp_http_client_write(client_, body_data + written, write_len - written);
                if (n <= 0) {
                    ESP_LOGE("EspHttp", "POST/PUT short write: got=%d need=%d", n, write_len - written);
                    OtaTlsDiag::LogStage(diag_attempt_id_, "http_write_fail");
                    Close();
                    return false;
                }
                written += n;
            }
            if (written != write_len) {
                ESP_LOGE("EspHttp", "POST/PUT incomplete write: %d/%d", written, write_len);
                OtaTlsDiag::LogStage(diag_attempt_id_, "http_write_short");
                Close();
                return false;
            }
        }

        content_length_ = esp_http_client_fetch_headers(client_);
        if (content_length_ < 0) {
            ESP_LOGE("EspHttp", "failed to fetch response headers: %d",
                     content_length_);
            OtaTlsDiag::LogStage(diag_attempt_id_, "http_headers_fail");
            Close();
            return false;
        }
        OtaTlsDiag::LogStage(diag_attempt_id_, "http_open_ok");
        return true;
    }

    int Write(const char* data, size_t len) override {
        if (!client_) return -1;
        if (len == 0) return 0; // compatibility; body framing is SetContent/Open
        return esp_http_client_write(client_, data, len);
    }

    int GetStatusCode() override {
        if (!client_) return -1;
        return esp_http_client_get_status_code(client_);
    }

    int GetBodyLength() override {
        return (int)content_length_;
    }

    int Read(char* buffer, size_t len) override {
        if (!client_) return -1;
        return esp_http_client_read(client_, buffer, len);
    }

    std::string ReadAll() override {
        std::string result;
        char buf[512];
        int len;
        while ((len = esp_http_client_read(client_, buf, sizeof(buf))) > 0) {
            result.append(buf, len);
        }
        return result;
    }

    void Close() override {
        if (client_) {
            OtaTlsDiag::LogClose(diag_attempt_id_, "EspHttp::Close");
            esp_http_client_close(client_);
            esp_http_client_cleanup(client_);
            client_ = nullptr;
        }
    }

private:
    static esp_err_t HttpEventHandler(esp_http_client_event_t* evt) {
        if (evt == nullptr || evt->user_data == nullptr) {
            return ESP_OK;
        }
        auto* self = static_cast<EspHttp*>(evt->user_data);
        if (evt->event_id == HTTP_EVENT_ERROR && evt->client != nullptr) {
            // Official API only — do not cast evt->data.
            int tls_code = 0;
            int tls_flags = 0;
            esp_err_t esp_tls_err =
                esp_http_client_get_and_clear_last_tls_error(evt->client, &tls_code, &tls_flags);
            self->last_esp_tls_err_ = esp_tls_err;
            self->last_mbedtls_err_ = tls_code;
            self->last_tls_flags_ = tls_flags;
            self->last_errno_ = errno;
            OtaTlsDiag::LogTlsError(self->diag_attempt_id_, self->last_open_err_, esp_tls_err,
                                    tls_code, tls_flags, errno);
        }
        return ESP_OK;
    }

    void CaptureTlsErrorFromClient() {
        if (!client_) {
            return;
        }
        int tls_code = 0;
        int tls_flags = 0;
        esp_err_t esp_tls_err =
            esp_http_client_get_and_clear_last_tls_error(client_, &tls_code, &tls_flags);
        // Prefer freshest capture; event handler may have already filled these.
        if (tls_code != 0 || esp_tls_err != ESP_OK) {
            last_esp_tls_err_ = esp_tls_err;
            last_mbedtls_err_ = tls_code;
            last_tls_flags_ = tls_flags;
        }
        if (last_errno_ == 0) {
            last_errno_ = errno;
        }
    }

    esp_http_client_handle_t client_ = nullptr;
    std::vector<std::pair<std::string, std::string>> headers_;
    std::string content_;
    CameraMultipartBody photo_content_;
    bool photo_content_active_ = false;
    int64_t content_length_ = 0;
    uint32_t diag_attempt_id_ = 0;
    esp_err_t last_open_err_ = ESP_OK;
    esp_err_t last_esp_tls_err_ = ESP_OK;
    int last_mbedtls_err_ = 0;
    int last_tls_flags_ = 0;
    int last_errno_ = 0;
};


// ─── WebSocket 实现 ───────────────────────────────────────────────────────────

class EspWebSocket : public WebSocket {
public:
    EspWebSocket() = default;
    ~EspWebSocket() override {
        if (client_) {
            esp_websocket_client_stop(client_);
            esp_websocket_client_destroy(client_);
        }
    }

    void SetHeader(const char* key, const char* value) override {
        extra_headers_ += std::string(key) + ": " + value + "\r\n";
    }

    bool Connect(const char* url, int timeout_ms) override {
        if (timeout_ms < 100) timeout_ms = 100;
        esp_websocket_client_config_t config = {};
        config.uri = url;
        config.disable_auto_reconnect = true;
        config.network_timeout_ms = timeout_ms;
        config.task_prio = 7;
        config.task_stack = 6 * 1024;
        config.task_name = "websocket";
        config.ping_interval_sec = 15;
        config.pingpong_timeout_sec = 60;
        config.disable_pingpong_discon = false;
        config.crt_bundle_attach = esp_crt_bundle_attach;
        if (!extra_headers_.empty()) {
            config.headers = extra_headers_.c_str();
        }
        client_ = esp_websocket_client_init(&config);
        if (!client_) return false;

        connected_at_us_ = 0;
        last_tx_ok_us_ = 0;
        last_rx_ok_us_ = 0;
        last_close_code_ = -1;
        last_close_reason_.clear();
        last_error_ = 0;
        last_send_transient_ = false;
        last_error_type_ = WEBSOCKET_ERROR_TYPE_NONE;
        last_tls_esp_err_ = ESP_OK;
        last_tls_stack_err_ = 0;
        last_sock_errno_ = 0;
        ctrl_ping_seen_ = 0;
        ctrl_pong_seen_ = 0;

        esp_websocket_register_events(client_, WEBSOCKET_EVENT_ANY,
            [](void* arg, esp_event_base_t, int32_t event_id, void* event_data) {
                auto* self = static_cast<EspWebSocket*>(arg);
                auto* data = static_cast<esp_websocket_event_data_t*>(event_data);
                if (event_id == WEBSOCKET_EVENT_CONNECTED) {
                    self->connected_ = true;
                    self->connected_at_us_ = esp_timer_get_time();
                    self->last_error_ = 0;
                    self->last_send_transient_ = false;
                    ESP_LOGI("EspWS", "[WS_DIAG] event=CONNECTED event_id=%ld",
                             (long)event_id);
                } else if (event_id == WEBSOCKET_EVENT_ERROR) {
                    self->CaptureErrorHandle(data);
                    self->LogDiagnosticsInternal("ERROR", -1, event_id);
                } else if (event_id == WEBSOCKET_EVENT_DISCONNECTED) {
                    self->connected_ = false;
                    self->CaptureErrorHandle(data);
                    self->ResetReceiveState();
                    self->LogDiagnosticsInternal("DISCONNECTED", -1, event_id);
                    if (self->on_disconnected_) self->on_disconnected_();
                } else if (event_id == WEBSOCKET_EVENT_CLOSED) {
                    self->connected_ = false;
                    self->CaptureErrorHandle(data);
                    self->LogDiagnosticsInternal("CLOSED", -1, event_id);
                } else if (event_id == WEBSOCKET_EVENT_DATA) {
                    self->HandleData(data);
                } else {
                    ESP_LOGD("EspWS", "[WS_DIAG] event_id=%ld", (long)event_id);
                }
            }, this);

        esp_err_t err = esp_websocket_client_start(client_);
        if (err != ESP_OK) {
            last_error_ = static_cast<int>(err);
            return false;
        }

        const int slices = (timeout_ms + 99) / 100;
        for (int i = 0; i < slices && !connected_; i++) {
            vTaskDelay(pdMS_TO_TICKS(100));
        }
        return connected_;
    }

    bool Send(const std::string& text) override {
        if (!client_ || !connected_) {
            last_send_transient_ = false;
            last_error_ = ENOTCONN;
            return false;
        }
        errno = 0;
        int sent = esp_websocket_client_send_text(
            client_, text.c_str(), (int)text.size(),
            pdMS_TO_TICKS(kControlSendTimeoutMs));
        return FinalizeSend(sent, (int)text.size(), errno);
    }

    bool Send(const void* data, size_t len, bool binary) override {
        if (!client_ || !connected_) {
            last_send_transient_ = false;
            last_error_ = ENOTCONN;
            return false;
        }
        const TickType_t timeout = binary
            ? pdMS_TO_TICKS(CONFIG_WS_AUDIO_SEND_TIMEOUT_MS)
            : pdMS_TO_TICKS(kControlSendTimeoutMs);
        const int64_t start_us = esp_timer_get_time();
        int sent;
        errno = 0;
        if (binary) {
            sent = esp_websocket_client_send_bin(
                client_, static_cast<const char*>(data), (int)len, timeout);
        } else {
            sent = esp_websocket_client_send_text(
                client_, static_cast<const char*>(data), (int)len, timeout);
        }
        const int send_errno = errno;
        const uint32_t elapsed_ms =
            (uint32_t)((esp_timer_get_time() - start_us) / 1000);
        const bool ok = FinalizeSend(sent, (int)len, send_errno);
        if (!ok || elapsed_ms > kSlowSendLogThresholdMs) {
            LogWsAudioSend((int)len, sent, elapsed_ms, /*send_queue_depth=*/-1);
        }
        return ok;
    }

    bool IsConnected() const override { return connected_; }
    int GetLastError() const override { return last_error_; }
    bool WasLastSendTransient() const override { return last_send_transient_; }
    const char* LastSendTransientClass() const override {
        return last_send_transient_class_;
    }
    void NoteRxOk() override { last_rx_ok_us_ = esp_timer_get_time(); }

    int64_t ConnectionAgeMs() const override {
        if (connected_at_us_ <= 0) return 0;
        return (esp_timer_get_time() - connected_at_us_) / 1000;
    }

    void LogDiagnostics(const char* reason, int send_queue_depth) override {
        LogDiagnosticsInternal(reason, send_queue_depth, -1);
    }

    void OnData(std::function<void(const char*, size_t, bool)> cb) override {
        on_data_ = std::move(cb);
    }

    void OnDisconnected(std::function<void()> cb) override {
        on_disconnected_ = std::move(cb);
    }

    static void NoteWifiDisconnectReason(int reason) {
        last_wifi_disconnect_reason_ = reason;
    }

private:
    static constexpr int kControlSendTimeoutMs = 5000;
    static constexpr int kSlowSendLogThresholdMs = 100;
    static constexpr int kMinWsAudioLogIntervalMs = 1000;
    static constexpr size_t kMaxWsMessageBytes = 256 * 1024;

    bool FinalizeSend(int sent, int requested, int sock_err) {
        if (sent == requested) {
            last_tx_ok_us_ = esp_timer_get_time();
            last_send_transient_ = false;
            last_send_transient_class_ = "";
            transient_fail_since_us_ = 0;
            last_error_ = 0;
            return true;
        }
        // Distinguish not-started classes. errno alone cannot separate
        // lock-timeout from pre-write poll timeout; the client return codes do.
        // Partial writes still return other negative/short values and must not
        // be treated as safe drops.
        if (connected_ && sent == ESP_WEBSOCKET_CLIENT_SEND_TX_LOCK_TIMEOUT) {
            last_send_transient_ = true;
            last_send_transient_class_ = "tx_lock_timeout";
            sock_err = EAGAIN;
        } else if (connected_ && sent == ESP_WEBSOCKET_CLIENT_SEND_NOT_STARTED) {
            last_send_transient_ = true;
            last_send_transient_class_ = "socket_not_writable";
            sock_err = EAGAIN;
        } else {
            last_send_transient_ = false;
            last_send_transient_class_ = "";
            transient_fail_since_us_ = 0;
        }
        if (last_send_transient_ && transient_fail_since_us_ == 0) {
            transient_fail_since_us_ = esp_timer_get_time();
        }
        last_sock_errno_ = sock_err;
        last_error_ = sock_err != 0 ? sock_err : EIO;
        return false;
    }

    void CaptureErrorHandle(const esp_websocket_event_data_t* data) {
        if (!data) return;
        last_error_type_ = data->error_handle.error_type;
        last_tls_esp_err_ = data->error_handle.esp_tls_last_esp_err;
        last_tls_stack_err_ = data->error_handle.esp_tls_stack_err;
        last_sock_errno_ = data->error_handle.esp_transport_sock_errno;
        if (last_sock_errno_ != 0) {
            last_error_ = last_sock_errno_;
        } else if (last_tls_esp_err_ != ESP_OK) {
            last_error_ = static_cast<int>(last_tls_esp_err_);
        } else if (last_error_type_ != WEBSOCKET_ERROR_TYPE_NONE) {
            last_error_ = static_cast<int>(last_error_type_);
        }
    }

    void LogDiagnosticsInternal(const char* reason, int send_queue_depth,
                                int32_t event_id) {
        int wifi_reason = last_wifi_disconnect_reason_;
        int rssi = 0;
        char ip[24] = {0};
        wifi_ap_record_t ap = {};
        if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
            rssi = ap.rssi;
        }
        esp_netif_t* netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
        if (netif) {
            esp_netif_ip_info_t ip_info;
            if (esp_netif_get_ip_info(netif, &ip_info) == ESP_OK) {
                snprintf(ip, sizeof(ip), IPSTR, IP2STR(&ip_info.ip));
            }
        }

        size_t free_heap = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
        size_t largest = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
        UBaseType_t ws_stack = 0;
        TaskHandle_t cur = xTaskGetCurrentTaskHandle();
        if (cur) ws_stack = uxTaskGetStackHighWaterMark(cur);

        const int64_t now = esp_timer_get_time();
        // Keep diagnostic values bounded to the native printf widths used by
        // newlib-nano. -1 continues to mean that no TX/RX timestamp exists.
        const int64_t raw_age_ms = ConnectionAgeMs();
        const uint32_t age_ms = static_cast<uint32_t>(
            raw_age_ms <= 0 ? 0 : (raw_age_ms > 0xFFFFFFFFLL ? 0xFFFFFFFFU : raw_age_ms));
        const auto last_activity_age_ms = [now](int64_t timestamp_us) -> long {
            if (timestamp_us <= 0) {
                return -1L;
            }
            const int64_t elapsed_ms = (now - timestamp_us) / 1000;
            return static_cast<long>(elapsed_ms > 2147483647LL ? 2147483647L
                                                                : (elapsed_ms < 0 ? 0 : elapsed_ms));
        };
        const long last_tx_age = last_activity_age_ms(last_tx_ok_us_);
        const long last_rx_age = last_activity_age_ms(last_rx_ok_us_);

        ESP_LOGW("EspWS",
                 "[WS_DIAG] reason=%s event_id=%ld close_code=%d "
                 "close_reason_len=%u sock_errno=%d tls_esp_err=0x%x "
                 "tls_stack_err=0x%x err_type=%d wifi_disc_reason=%d rssi=%d "
                 "ip=%s age_ms=%u last_tx_age_ms=%ld last_rx_age_ms=%ld "
                 "send_q=%d free_heap=%u largest_block=%u task_stack_hwm=%u "
                 "ctrl_ping=%u ctrl_pong=%u connected=%d",
                 reason ? reason : "-",
                 (long)event_id,
                 last_close_code_,
                 static_cast<unsigned>(last_close_reason_.size()),
                 last_sock_errno_,
                 static_cast<unsigned>(last_tls_esp_err_),
                 last_tls_stack_err_,
                 static_cast<int>(last_error_type_),
                 wifi_reason, rssi, ip[0] ? ip : "-",
                 static_cast<unsigned>(age_ms), last_tx_age,
                 last_rx_age, send_queue_depth,
                 static_cast<unsigned>(free_heap),
                 static_cast<unsigned>(largest),
                 static_cast<unsigned>(ws_stack),
                 ctrl_ping_seen_, ctrl_pong_seen_,
                 connected_ ? 1 : 0);
    }

    void LogWsAudioSend(int requested_bytes, int returned_bytes,
                        uint32_t elapsed_ms, int send_queue_depth) {
        TickType_t now = xTaskGetTickCount();
        if ((TickType_t)(now - last_ws_audio_log_tick_) <
            pdMS_TO_TICKS(kMinWsAudioLogIntervalMs)) {
            return;
        }
        last_ws_audio_log_tick_ = now;
        const int64_t now_us = esp_timer_get_time();
        long last_tx_age_ms = -1;
        if (last_tx_ok_us_ > 0) {
            const int64_t age = (now_us - last_tx_ok_us_) / 1000;
            last_tx_age_ms = static_cast<long>(
                age > 2147483647LL ? 2147483647L : (age < 0 ? 0 : age));
        }
        long fail_for_ms = -1;
        if (transient_fail_since_us_ > 0) {
            const int64_t age = (now_us - transient_fail_since_us_) / 1000;
            fail_for_ms = static_cast<long>(
                age > 2147483647LL ? 2147483647L : (age < 0 ? 0 : age));
        }
        const char* fail_class =
            last_send_transient_class_[0] ? last_send_transient_class_
                                          : (last_send_transient_ ? "transient"
                                                                  : "fatal");
        ESP_LOGW("EspWS",
                 "[WS_AUDIO] requested_bytes=%d returned_bytes=%d "
                 "elapsed_ms=%u transient=%d fail_class=%s "
                 "fail_for_ms=%ld last_tx_age_ms=%ld send_q=%d",
                 requested_bytes, returned_bytes, (unsigned)elapsed_ms,
                 last_send_transient_ ? 1 : 0, fail_class, fail_for_ms,
                 last_tx_age_ms, send_queue_depth);
    }

    void HandleData(const esp_websocket_event_data_t* data) {
        if (data == nullptr) {
            ResetReceiveState();
            return;
        }

        const int data_len = data->data_len;
        const int payload_len = data->payload_len;
        const int payload_offset = data->payload_offset;

        if (data_len < 0 || payload_len < 0 || payload_offset < 0 ||
            payload_offset > payload_len ||
            data_len > payload_len - payload_offset) {
            ESP_LOGW("EspWS",
                     "ws: invalid event bounds off=%d len=%d total=%d, dropping",
                     payload_offset, data_len, payload_len);
            ResetReceiveState();
            return;
        }

        const uint8_t op = data->op_code;
        const bool is_data_frame = (op == WS_TRANSPORT_OPCODES_TEXT ||
                                    op == WS_TRANSPORT_OPCODES_BINARY ||
                                    op == WS_TRANSPORT_OPCODES_CONT);

        if (payload_offset == 0) {
            if (frame_in_progress_) {
                ESP_LOGW("EspWS",
                         "ws: frame interrupted before completion, dropping");
                ResetReceiveState();
            }

            if (!is_data_frame) {
                // Observe only — transport still auto-replies to Ping.
                if (op == WS_TRANSPORT_OPCODES_PING) {
                    ++ctrl_ping_seen_;
                    ESP_LOGI("EspWS",
                             "[WS_DIAG] ctrl_frame=PING len=%d "
                             "(transport auto-pong)",
                             data_len);
                } else if (op == WS_TRANSPORT_OPCODES_PONG) {
                    ++ctrl_pong_seen_;
                    ESP_LOGI("EspWS", "[WS_DIAG] ctrl_frame=PONG len=%d",
                             data_len);
                } else if (op == WS_TRANSPORT_OPCODES_CLOSE) {
                    last_close_code_ = 1005;
                    last_close_reason_.clear();
                    if (data_len >= 2 && data->data_ptr) {
                        last_close_code_ =
                            (static_cast<uint8_t>(data->data_ptr[0]) << 8) |
                            static_cast<uint8_t>(data->data_ptr[1]);
                        if (data_len > 2) {
                            size_t n = static_cast<size_t>(data_len - 2);
                            if (n > 64) n = 64;
                            last_close_reason_.assign(data->data_ptr + 2, n);
                        }
                    }
                    ESP_LOGW("EspWS",
                             "[WS_DIAG] ctrl_frame=CLOSE code=%d reason_len=%u",
                             last_close_code_,
                             static_cast<unsigned>(last_close_reason_.size()));
                }
                return;
            }

            if (op == WS_TRANSPORT_OPCODES_CONT) {
                if (!rx_in_progress_) {
                    ESP_LOGW("EspWS", "ws: orphan continuation frame, dropping");
                    ResetReceiveState();
                    return;
                }
            } else {
                rx_fragment_.clear();
                rx_in_progress_ = true;
                rx_is_binary_ = (op == WS_TRANSPORT_OPCODES_BINARY);
            }

            frame_in_progress_ = true;
            frame_received_ = 0;
        } else {
            if (!frame_in_progress_ || !rx_in_progress_) {
                ESP_LOGW("EspWS",
                         "ws: unexpected mid-frame chunk (off=%d), dropping",
                         payload_offset);
                ResetReceiveState();
                return;
            }
            if (payload_offset != frame_received_) {
                ESP_LOGW("EspWS",
                         "ws: frame chunk gap/dup (off=%d expected=%d), dropping",
                         payload_offset, frame_received_);
                ResetReceiveState();
                return;
            }
        }

        if (data_len > 0 && data->data_ptr != nullptr) {
            if (rx_fragment_.size() + static_cast<size_t>(data_len) >
                kMaxWsMessageBytes) {
                ESP_LOGW("EspWS",
                         "ws: oversized message (have=%u + chunk=%d > %u), "
                         "dropping",
                         static_cast<unsigned>(rx_fragment_.size()), data_len,
                         static_cast<unsigned>(kMaxWsMessageBytes));
                ResetReceiveState();
                return;
            }
            rx_fragment_.insert(
                rx_fragment_.end(),
                reinterpret_cast<const uint8_t*>(data->data_ptr),
                reinterpret_cast<const uint8_t*>(data->data_ptr) + data_len);
        }
        frame_received_ += data_len;

        if (payload_offset + data_len < payload_len) {
            return;
        }

        frame_in_progress_ = false;
        frame_received_ = 0;

        if (!data->fin) {
            return;
        }

        const bool binary = rx_is_binary_;
        std::vector<uint8_t> msg = std::move(rx_fragment_);
        rx_fragment_.clear();
        rx_in_progress_ = false;
        if (on_data_ && !msg.empty()) {
            last_rx_ok_us_ = esp_timer_get_time();
            on_data_(reinterpret_cast<const char*>(msg.data()), msg.size(),
                     binary);
        }
    }

    void ResetReceiveState() {
        rx_fragment_.clear();
        rx_in_progress_ = false;
        rx_is_binary_ = false;
        frame_in_progress_ = false;
        frame_received_ = 0;
    }

    esp_websocket_client_handle_t client_ = nullptr;
    std::string extra_headers_;
    volatile bool connected_ = false;
    int last_error_ = 0;
    bool last_send_transient_ = false;
    const char* last_send_transient_class_ = "";
    int64_t transient_fail_since_us_ = 0;
    TickType_t last_ws_audio_log_tick_ = 0;
    std::function<void(const char*, size_t, bool)> on_data_;
    std::function<void()> on_disconnected_;

    int64_t connected_at_us_ = 0;
    int64_t last_tx_ok_us_ = 0;
    int64_t last_rx_ok_us_ = 0;
    int last_close_code_ = -1;
    std::string last_close_reason_;
    esp_websocket_error_type_t last_error_type_ = WEBSOCKET_ERROR_TYPE_NONE;
    esp_err_t last_tls_esp_err_ = ESP_OK;
    int last_tls_stack_err_ = 0;
    int last_sock_errno_ = 0;
    uint32_t ctrl_ping_seen_ = 0;
    uint32_t ctrl_pong_seen_ = 0;
    static inline int last_wifi_disconnect_reason_ = 0;

    std::vector<uint8_t> rx_fragment_;
    bool rx_in_progress_ = false;
    bool rx_is_binary_ = false;
    bool frame_in_progress_ = false;
    int frame_received_ = 0;
};

// ─── Mqtt 实现 ────────────────────────────────────────────────────────────────

class EspMqtt : public Mqtt {
public:
    EspMqtt() = default;
    ~EspMqtt() override {
        if (client_) {
            esp_mqtt_client_stop(client_);
            esp_mqtt_client_destroy(client_);
        }
    }

    void SetKeepAlive(int seconds) override { keepalive_ = seconds; }

    bool Connect(const std::string& host, int port,
                 const std::string& client_id,
                 const std::string& username,
                 const std::string& password) override {
        esp_mqtt_client_config_t config = {};
        config.broker.address.hostname = host.c_str();
        config.broker.address.port = port;
        config.broker.address.transport = (port == 8883)
            ? MQTT_TRANSPORT_OVER_SSL : MQTT_TRANSPORT_OVER_TCP;
        config.credentials.client_id = client_id.c_str();
        if (!username.empty()) config.credentials.username = username.c_str();
        if (!password.empty()) config.credentials.authentication.password = password.c_str();
        config.session.keepalive = keepalive_;
        config.session.disable_clean_session = false;

        client_ = esp_mqtt_client_init(&config);
        if (!client_) return false;

        esp_mqtt_client_register_event(client_, MQTT_EVENT_ANY,
            [](void* arg, esp_event_base_t, int32_t event_id, void* event_data) {
                auto* self = static_cast<EspMqtt*>(arg);
                auto* data = static_cast<esp_mqtt_event_handle_t>(event_data);
                if (event_id == MQTT_EVENT_CONNECTED) {
                    if (self->on_connected_) self->on_connected_();
                } else if (event_id == MQTT_EVENT_DISCONNECTED) {
                    if (self->on_disconnected_) self->on_disconnected_();
                } else if (event_id == MQTT_EVENT_DATA) {
                    if (self->on_message_) {
                        std::string topic(data->topic, data->topic_len);
                        std::string payload(data->data, data->data_len);
                        self->on_message_(topic, payload);
                    }
                }
            }, this);

        esp_err_t err = esp_mqtt_client_start(client_);
        return err == ESP_OK;
    }

    bool IsConnected() const override { return connected_; }
    int GetLastError() const override { return 0; }

    bool Subscribe(const std::string& topic) override {
        if (!client_) return false;
        return esp_mqtt_client_subscribe(client_, topic.c_str(), 0) >= 0;
    }

    bool Publish(const std::string& topic, const std::string& payload) override {
        if (!client_) return false;
        return esp_mqtt_client_publish(client_, topic.c_str(),
                                       payload.c_str(), payload.size(), 0, 0) >= 0;
    }

    void OnConnected(std::function<void()> cb) override { on_connected_ = std::move(cb); }
    void OnDisconnected(std::function<void()> cb) override { on_disconnected_ = std::move(cb); }
    void OnMessage(std::function<void(const std::string&, const std::string&)> cb) override {
        on_message_ = std::move(cb);
    }

private:
    esp_mqtt_client_handle_t client_ = nullptr;
    int keepalive_ = 120;
    volatile bool connected_ = false;
    std::function<void()> on_connected_;
    std::function<void()> on_disconnected_;
    std::function<void(const std::string&, const std::string&)> on_message_;
};

// ─── Udp 实现 ─────────────────────────────────────────────────────────────────

class EspUdp : public Udp {
public:
    EspUdp() = default;
    ~EspUdp() override {
        if (sock_ >= 0) close(sock_);
    }

    bool Connect(const std::string& host, int port) override {
        struct addrinfo hints = {}, *res = nullptr;
        hints.ai_family = AF_INET;
        hints.ai_socktype = SOCK_DGRAM;
        char port_str[8];
        snprintf(port_str, sizeof(port_str), "%d", port);
        if (getaddrinfo(host.c_str(), port_str, &hints, &res) != 0 || !res) return false;

        sock_ = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
        if (sock_ < 0) { freeaddrinfo(res); return false; }

        memcpy(&remote_addr_, res->ai_addr, res->ai_addrlen);
        remote_addr_len_ = res->ai_addrlen;
        freeaddrinfo(res);
        return true;
    }

    int Send(const std::string& data) override {
        if (sock_ < 0) return -1;
        return sendto(sock_, data.data(), data.size(), 0,
                      (struct sockaddr*)&remote_addr_, remote_addr_len_);
    }

    void OnMessage(std::function<void(const std::string&)> cb) override {
        on_message_ = std::move(cb);
        // 启动接收任务
        TaskHandle_t udp_rx_handle = nullptr;
        xTaskCreate([](void* arg) {
            task_diag::LogCurrentTask("EspUdp", "udp_rx_start", 5, -1);
            auto* self = static_cast<EspUdp*>(arg);
            char buf[2048];
            while (self->sock_ >= 0) {
                int len = recv(self->sock_, buf, sizeof(buf), 0);
                if (len > 0 && self->on_message_) {
                    self->on_message_(std::string(buf, len));
                }
            }
            vTaskDelete(nullptr);
        }, "udp_rx", 4096, this, 5, &udp_rx_handle);
        task_diag::LogTaskHandle("EspUdp", "udp_rx_created", udp_rx_handle, 5, -1);
    }

private:
    int sock_ = -1;
    struct sockaddr_storage remote_addr_ = {};
    socklen_t remote_addr_len_ = 0;
    std::function<void(const std::string&)> on_message_;
};

// ─── EspNetwork：NetworkInterface 的 WiFi 实现 ────────────────────────────────

class EspNetwork : public NetworkInterface {
public:
    std::unique_ptr<Http> CreateHttp(int /*index*/) override {
        return std::make_unique<EspHttp>();
    }
    std::unique_ptr<WebSocket> CreateWebSocket(int /*index*/) override {
        return std::make_unique<EspWebSocket>();
    }
    std::unique_ptr<Mqtt> CreateMqtt(int /*index*/) override {
        return std::make_unique<EspMqtt>();
    }
    std::unique_ptr<Udp> CreateUdp(int /*index*/) override {
        return std::make_unique<EspUdp>();
    }
};
