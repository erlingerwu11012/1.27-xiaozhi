#include "websocket_protocol.h"
#include "board.h"
#include "system_info.h"
#include "application.h"
#include "ota.h"
#include "settings.h"
#include "face_roster.h"
#include "vision_credentials.h"
#include "websocket_connection_gate.h"

#include <cstring>
#include <cJSON.h>
#include <esp_log.h>
#include <arpa/inet.h>
#include "assets/lang_config.h"

#define TAG "WS"

WebsocketProtocol::WebsocketProtocol() {
    event_group_handle_ = xEventGroupCreate();
}

WebsocketProtocol::~WebsocketProtocol() {
    vEventGroupDelete(event_group_handle_);
}

bool WebsocketProtocol::Start() {
    // Only connect to server when audio channel is needed
    return true;
}

bool WebsocketProtocol::SendAudio(std::unique_ptr<AudioStreamPacket> packet) {
    bool send_failed = false;
    bool sent = false;
    bool transient = false;
    {
        // Hold ws_mutex_ across the (potentially blocking) send so a concurrent
        // CloseAudioChannel() cannot reset/destroy websocket_ underneath us.
        std::lock_guard<std::mutex> lock(ws_mutex_);
        if (websocket_ == nullptr || !websocket_->IsConnected()) {
            // Channel already closed (e.g. listening timeout → idle). Drop the
            // packet quietly; do not surface SERVER_ERROR / "请检查网络".
            return false;
        } else {
            auto do_send = [this, &packet]() -> bool {
                if (version_ == 2) {
                    std::string serialized;
                    serialized.resize(sizeof(BinaryProtocol2) + packet->payload.size());
                    auto bp2 = (BinaryProtocol2*)serialized.data();
                    bp2->version = htons(version_);
                    bp2->type = 0;
                    bp2->reserved = 0;
                    bp2->timestamp = htonl(packet->timestamp);
                    bp2->payload_size = htonl(packet->payload.size());
                    memcpy(bp2->payload, packet->payload.data(), packet->payload.size());
                    return websocket_->Send(serialized.data(), serialized.size(), true);
                }
                if (version_ == 3) {
                    std::string serialized;
                    serialized.resize(sizeof(BinaryProtocol3) + packet->payload.size());
                    auto bp3 = (BinaryProtocol3*)serialized.data();
                    bp3->type = 0;
                    bp3->reserved = 0;
                    bp3->payload_size = htons(packet->payload.size());
                    memcpy(bp3->payload, packet->payload.data(), packet->payload.size());
                    return websocket_->Send(serialized.data(), serialized.size(), true);
                }
                return websocket_->Send(packet->payload.data(), packet->payload.size(), true);
            };

            sent = do_send();
            if (!sent) {
                transient = websocket_->WasLastSendTransient();
                send_failed = true;
                if (transient) {
                    if (consecutive_transient_failures_ < UINT32_MAX) {
                        ++consecutive_transient_failures_;
                    }
                    if (consecutive_transient_failures_ <= 3 ||
                        consecutive_transient_failures_ % 20 == 0) {
                        const char* fail_class = websocket_->LastSendTransientClass();
                        if (!fail_class || !fail_class[0]) {
                            fail_class = "transient";
                        }
                        ESP_LOGW(TAG,
                                 "[WS_AUDIO] transient_send_fail count=%u "
                                 "fail_class=%s action=drop_packet_keep_link",
                                 (unsigned)consecutive_transient_failures_,
                                 fail_class);
                    }
                }
            } else {
                consecutive_transient_failures_ = 0;
            }
        }
    }

    if (send_failed) {
        if (transient) {
            // Failure count is diagnostic only. Transport errors and heartbeat
            // liveness, not a handful of untouched audio packets, end a session.
            return false;
        }
        HandleAudioSendFailure();
    }
    return sent;
}

void WebsocketProtocol::HandleAudioSendFailure() {
    size_t encode_q = 0, send_q = 0;
    // Best-effort queue depth for diagnostics (Application owns AudioService).
    Application::GetInstance().GetAudioQueueStats(encode_q, send_q);
    {
        std::lock_guard<std::mutex> lock(ws_mutex_);
        if (websocket_) {
            websocket_->LogDiagnostics("audio_send_fatal", static_cast<int>(send_q));
        }
    }
    // stop/destroy may wait for the WS task to exit. Stop producing upload
    // audio first so that this wait cannot fill both queues while disconnected.
    auto& audio = Application::GetInstance().GetAudioService();
    audio.EnableVoiceProcessing(false);
    audio.ResetUploadQueues();
    CloseAudioChannel();
    if (!error_occurred_) {
        SetError(Lang::Strings::SERVER_ERROR);
    }
}

bool WebsocketProtocol::SendText(const std::string& text) {
    bool sent = false;
    bool channel_open = false;
    {
        std::lock_guard<std::mutex> lock(ws_mutex_);
        channel_open = websocket_ != nullptr && websocket_->IsConnected();
        if (channel_open) {
            sent = websocket_->Send(text);
        }
    }

    if (!channel_open) {
        // Intentional idle/close: do not alarm as a network failure.
        ESP_LOGW(TAG, "Skip send text (channel closed, len=%u)",
                 static_cast<unsigned>(text.size()));
        return false;
    }
    if (!sent) {
        ESP_LOGE(TAG, "Failed to send text (len=%u)", static_cast<unsigned>(text.size()));
        SetError(Lang::Strings::SERVER_ERROR);
        return false;
    }

    return true;
}

bool WebsocketProtocol::IsAudioChannelOpened() const {
    std::lock_guard<std::mutex> lock(ws_mutex_);
    return websocket_ != nullptr && websocket_->IsConnected() && !error_occurred_ && !IsTimeout();
}

void WebsocketProtocol::CloseAudioChannel() {
    ESP_LOGI(TAG, "Closing websocket audio channel");
    std::unique_ptr<WebSocket> doomed;
    {
        std::lock_guard<std::mutex> lock(ws_mutex_);
        if (websocket_) {
            websocket_->LogDiagnostics("local_close", -1);
        }
        consecutive_transient_failures_ = 0;
        // Destroy outside the mutex so DISCONNECTED callbacks cannot deadlock.
        doomed = std::move(websocket_);
    }
    doomed.reset();
}

bool WebsocketProtocol::NeedsCredentialRefresh() const {
    return authconn::PersistedRefreshRequested();
}

void WebsocketProtocol::AcceptRefreshedCredentials() {
    authconn::ClearPersistedRefreshRequest();
    terminal_auth_rejected_.store(false);
}

bool WebsocketProtocol::OpenAudioChannel() {
    if (terminal_auth_rejected_.load()) {
        ESP_LOGW(TAG, "[WS_AUTH] open_blocked reason=rebind_required");
        return false;
    }
    opened_credential_epoch_ = authconn::CurrentPersistedEpoch();

    Settings settings("websocket", false);
    std::string url = settings.GetString("url");
    std::string token = settings.GetString("token");
    int version = settings.GetInt("version");
    if (version != 0) {
        version_ = version;
    }

    error_occurred_ = false;
    consecutive_transient_failures_ = 0;
    // A prior connection's hello bit must never satisfy this connection's wait.
    xEventGroupClearBits(event_group_handle_, WEBSOCKET_PROTOCOL_SERVER_HELLO_EVENT);
    // Never reuse a session id from a previous connection. Each new link starts
    // a fresh handshake and the server assigns a new session.
    FaceRoster::GetInstance().MarkUnknown("channel_open");
    const uint32_t connection_generation =
        VisionCredentialStore::GetInstance().BeginConnection();
    connection_generation_ = connection_generation;
    connection_gate_.Begin(connection_generation, &session_id_);

    auto network = Board::GetInstance().GetNetwork();
    websocket_ = network->CreateWebSocket(1);
    if (websocket_ == nullptr) {
        ESP_LOGE(TAG, "Failed to create websocket");
        connection_gate_.End(connection_generation);
        VisionCredentialStore::GetInstance().EndConnection(connection_generation);
        return false;
    }

    if (!token.empty()) {
        // If token not has a space, add "Bearer " prefix
        if (token.find(" ") == std::string::npos) {
            token = "Bearer " + token;
        }
        websocket_->SetHeader("Authorization", token.c_str());
    }
    std::string proto_ver = std::to_string(version_);
    websocket_->SetHeader("Protocol-Version", proto_ver.c_str());
    std::string device_id = SystemInfo::GetMacAddress();
    websocket_->SetHeader("Device-Id", device_id.c_str());
    std::string client_id = Board::GetInstance().GetUuid();
    websocket_->SetHeader("Client-Id", client_id.c_str());

    websocket_->OnData([this, connection_generation](const char* data, size_t len, bool binary) {
        if (binary) {
            auto admission = connection_gate_.TryAdmit(connection_generation);
            if (!admission) {
                return;
            }
            // Release before audio callback: decoder / Schedule paths must not
            // run while Begin/End are blocked (same deadlock class as MCP).
            admission.Release();
            if (on_incoming_audio_ != nullptr) {
                if (version_ == 2) {
                    const auto* bp2 = reinterpret_cast<const BinaryProtocol2*>(data);
                    if (len < sizeof(BinaryProtocol2)) {
                        ESP_LOGE(TAG, "BinaryProtocol2 too short: len=%u < header=%u",
                                 static_cast<unsigned>(len), static_cast<unsigned>(sizeof(BinaryProtocol2)));
                        return;
                    }
                    const uint16_t version = ntohs(bp2->version);
                    const uint32_t payload_size = ntohl(bp2->payload_size);
                    const uint32_t timestamp = ntohl(bp2->timestamp);
                    if (version != 2) {
                        ESP_LOGE(TAG, "BinaryProtocol2 version mismatch: %u", static_cast<unsigned>(version));
                        return;
                    }
                    if (payload_size > len - sizeof(BinaryProtocol2)) {
                        ESP_LOGE(TAG, "BinaryProtocol2 payload_size=%u exceeds remaining=%u",
                                 static_cast<unsigned>(payload_size),
                                 static_cast<unsigned>(len - sizeof(BinaryProtocol2)));
                        return;
                    }
                    std::vector<uint8_t> payload_vec(bp2->payload, bp2->payload + payload_size);
                    on_incoming_audio_(std::make_unique<AudioStreamPacket>(AudioStreamPacket{
                        .sample_rate = server_sample_rate_,
                        .frame_duration = server_frame_duration_,
                        .timestamp = timestamp,
                        .payload = std::move(payload_vec)
                    }));
                } else if (version_ == 3) {
                    const auto* bp3 = reinterpret_cast<const BinaryProtocol3*>(data);
                    if (len < sizeof(BinaryProtocol3)) {
                        ESP_LOGE(TAG, "BinaryProtocol3 too short: len=%u < header=%u",
                                 static_cast<unsigned>(len), static_cast<unsigned>(sizeof(BinaryProtocol3)));
                        return;
                    }
                    const uint16_t payload_size = ntohs(bp3->payload_size);
                    if (payload_size > len - sizeof(BinaryProtocol3)) {
                        ESP_LOGE(TAG, "BinaryProtocol3 payload_size=%u exceeds remaining=%u",
                                 static_cast<unsigned>(payload_size),
                                 static_cast<unsigned>(len - sizeof(BinaryProtocol3)));
                        return;
                    }
                    std::vector<uint8_t> payload_vec(bp3->payload, bp3->payload + payload_size);
                    on_incoming_audio_(std::make_unique<AudioStreamPacket>(AudioStreamPacket{
                        .sample_rate = server_sample_rate_,
                        .frame_duration = server_frame_duration_,
                        .timestamp = 0,
                        .payload = std::move(payload_vec)
                    }));
                } else {
                    std::vector<uint8_t> payload_vec;
                    payload_vec.reserve(len);
                    payload_vec.assign((uint8_t*)data, (uint8_t*)data + len);
                    on_incoming_audio_(std::make_unique<AudioStreamPacket>(AudioStreamPacket{
                        .sample_rate = server_sample_rate_,
                        .frame_duration = server_frame_duration_,
                        .timestamp = 0,
                        .payload = std::move(payload_vec)
                    }));
                }
            }
            last_incoming_time_ = std::chrono::steady_clock::now();
            if (websocket_) {
                websocket_->NoteRxOk();
            }
            return;
        }

        // Text frames (hello / MCP / …): admit before any protocol state change.
        WebsocketTextDispatchHandlers handlers;
        handlers.on_hello = [this, connection_generation](const cJSON* root) {
            ParseServerHello(root, connection_generation);
        };
        handlers.on_terminal_auth = [this](const cJSON* root) {
            return HandleTerminalAuthError(root);
        };
        handlers.on_other = [this](const cJSON* root, uint32_t source_gen) {
            if (on_incoming_json_ != nullptr) {
                on_incoming_json_(root, source_gen);
            }
        };
        const auto dispatch = DispatchWebsocketTextFrame(
            connection_gate_, connection_generation, data, len, handlers);
        if (dispatch == WebsocketTextDispatchResult::kDiscardedStale) {
            return;
        }
        if (dispatch == WebsocketTextDispatchResult::kParseError) {
            ESP_LOGE(TAG, "Failed to parse JSON, len=%u",
                     static_cast<unsigned>(len));
        }
        last_incoming_time_ = std::chrono::steady_clock::now();
        if (websocket_) {
            websocket_->NoteRxOk();
        }
    });

    websocket_->OnDisconnected([this, connection_generation]() {
        // Do not take ws_mutex_ here: CloseAudioChannel may already hold it
        // while destroying this socket (stop → DISCONNECTED → this callback).
        ESP_LOGI(TAG, "Websocket disconnected");
        size_t encode_q = 0, send_q = 0;
        Application::GetInstance().GetAudioQueueStats(encode_q, send_q);
        if (websocket_) {
            websocket_->LogDiagnostics("on_disconnected", static_cast<int>(send_q));
        }
        VisionCredentialStore::GetInstance().EndConnection(connection_generation);
        std::string closed_session;
        if (!connection_gate_.End(connection_generation, &session_id_,
                                  &closed_session)) {
            ESP_LOGI(TAG,
                     "Ignoring stale disconnect closed_gen=%u current_gen=%u",
                     static_cast<unsigned>(connection_generation),
                     static_cast<unsigned>(connection_gate_.current_generation()));
            return;
        }
        Application::GetInstance().OnAudioSessionClosed(closed_session);
        if (on_audio_channel_closed_ != nullptr) {
            on_audio_channel_closed_(connection_generation);
        }
    });

    ESP_LOGI(TAG, "Connecting to websocket server: %s with version: %d", url.c_str(), version_);
    if (!websocket_->Connect(url.c_str())) {
        ESP_LOGE(TAG, "Failed to connect to websocket server, code=%d", websocket_->GetLastError());
        if (websocket_) {
            websocket_->LogDiagnostics("connect_failed", -1);
        }
        connection_gate_.End(connection_generation, &session_id_);
        VisionCredentialStore::GetInstance().EndConnection(connection_generation);
        SetError(Lang::Strings::SERVER_NOT_CONNECTED);
        return false;
    }

    auto message = GetHelloMessage();
    if (!SendText(message)) {
        connection_gate_.End(connection_generation, &session_id_);
        VisionCredentialStore::GetInstance().EndConnection(connection_generation);
        return false;
    }

    EventBits_t bits = xEventGroupWaitBits(event_group_handle_, WEBSOCKET_PROTOCOL_SERVER_HELLO_EVENT, pdTRUE, pdFALSE, pdMS_TO_TICKS(10000));
    if (!(bits & WEBSOCKET_PROTOCOL_SERVER_HELLO_EVENT)) {
        ESP_LOGE(TAG, "Failed to receive server hello");
        connection_gate_.End(connection_generation, &session_id_);
        VisionCredentialStore::GetInstance().EndConnection(connection_generation);
        SetError(Lang::Strings::SERVER_TIMEOUT);
        return false;
    }

    if (on_audio_channel_opened_ != nullptr) {
        on_audio_channel_opened_(connection_generation);
    }

    return true;
}

bool WebsocketProtocol::HandleTerminalAuthError(const cJSON* root) {
    const cJSON* type = cJSON_GetObjectItem(root, "type");
    const cJSON* code = cJSON_GetObjectItem(root, "code");
    if (!cJSON_IsString(type) || !type->valuestring ||
        strcmp(type->valuestring, "error") != 0 ||
        !cJSON_IsString(code) || !code->valuestring) {
        return false;
    }

    if (strcmp(code->valuestring, "token_expired") == 0) {
        const authconn::Outcome outcome =
            authconn::NotePersistedTokenExpired(opened_credential_epoch_);
        ESP_LOGW(TAG, "[WS_AUTH] token_expired action=%s epoch=%u",
                 authconn::ActionName(outcome.action),
                 static_cast<unsigned>(opened_credential_epoch_));
        return outcome.status != authconn::AuthStatus::kStale;
    }

    // DNS, TLS, timeouts and HTTP failures never reach this function.  Only
    // an explicit server auth code can retire the credential epoch that was
    // presented on this socket.
    const bool terminal =
        strcmp(code->valuestring, "device_unbound") == 0 ||
        strcmp(code->valuestring, "device_disabled") == 0 ||
        strcmp(code->valuestring, "credential_revoked") == 0;
    if (!terminal) {
        return false;
    }

    const authconn::Outcome outcome =
        authconn::ApplyPersistedTerminal(code->valuestring, opened_credential_epoch_);
    ESP_LOGW(TAG, "[WS_AUTH] terminal_rejection reason=%s status=%s epoch=%u",
             code->valuestring, authconn::StatusName(outcome.status),
             static_cast<unsigned>(opened_credential_epoch_));
    if (outcome.status == authconn::AuthStatus::kStale ||
        outcome.status == authconn::AuthStatus::kPersistFailed) {
        return true;
    }
    terminal_auth_rejected_.store(true);
    Application::GetInstance().Schedule([]() {
        Application::GetInstance().RecoverAuthAfterTerminal();
    });
    return true;
}

std::string WebsocketProtocol::GetHelloMessage() {
    // keys: message type, version, audio_params (format, sample_rate, channels)
    cJSON* root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", "hello");
    cJSON_AddNumberToObject(root, "version", version_);
    cJSON* features = cJSON_CreateObject();
#if CONFIG_USE_SERVER_AEC
    cJSON_AddBoolToObject(features, "aec", true);
#endif
    cJSON_AddBoolToObject(features, "mcp", true);
    cJSON_AddItemToObject(root, "features", features);
    cJSON_AddStringToObject(root, "transport", "websocket");
    cJSON* audio_params = cJSON_CreateObject();
    cJSON_AddStringToObject(audio_params, "format", "opus");
    cJSON_AddNumberToObject(audio_params, "sample_rate", 16000);
    cJSON_AddNumberToObject(audio_params, "channels", 1);
    cJSON_AddNumberToObject(audio_params, "frame_duration", OPUS_FRAME_DURATION_MS);
    cJSON_AddItemToObject(root, "audio_params", audio_params);
    auto json_str = cJSON_PrintUnformatted(root);
    std::string message(json_str);
    cJSON_free(json_str);
    cJSON_Delete(root);
    return message;
}

void WebsocketProtocol::ParseServerHello(const cJSON* root, uint32_t source_generation) {
    auto transport = cJSON_GetObjectItem(root, "transport");
    if (!cJSON_IsString(transport) || !transport->valuestring ||
        strcmp(transport->valuestring, "websocket") != 0) {
        ESP_LOGE(TAG, "Invalid server hello transport");
        return;
    }

    auto session_id = cJSON_GetObjectItem(root, "session_id");
    if (!cJSON_IsString(session_id) || !session_id->valuestring ||
        session_id->valuestring[0] == '\0' || strlen(session_id->valuestring) > 256) {
        ESP_LOGE(TAG, "Invalid server hello session");
        return;
    }
    // Dispatch holds the generation admission lock. Publish before waking the
    // opener so initialize-before-hello and hello-before-initialize both work.
    session_id_ = session_id->valuestring;
    VisionCredentialStore::GetInstance().ApplyHelloSession(source_generation, session_id_);
    ESP_LOGI(TAG, "Session ID: %s", session_id_.c_str());
    FaceRoster::GetInstance().OnAudioSessionOpened(session_id_);

    auto audio_params = cJSON_GetObjectItem(root, "audio_params");
    if (cJSON_IsObject(audio_params)) {
        auto sample_rate = cJSON_GetObjectItem(audio_params, "sample_rate");
        if (cJSON_IsNumber(sample_rate)) {
            server_sample_rate_ = sample_rate->valueint;
        }
        auto frame_duration = cJSON_GetObjectItem(audio_params, "frame_duration");
        if (cJSON_IsNumber(frame_duration)) {
            server_frame_duration_ = frame_duration->valueint;
        }
    }

    xEventGroupSetBits(event_group_handle_, WEBSOCKET_PROTOCOL_SERVER_HELLO_EVENT);
}
