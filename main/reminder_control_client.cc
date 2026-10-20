#include "reminder_control_client.h"

#include "application.h"
#include "board.h"
#include "presence_context.h"
#include "reminder_coordinator.h"
#include "reminder_voice_service.h"
#include "settings.h"
#include "system_info.h"
#include "user_context.h"
#include "web_socket.h"

#include <cJSON.h>
#include <esp_log.h>

#include <cctype>
#include <cmath>
#include <cstring>

namespace {
constexpr const char* kTag = "ReminderCtrl";
constexpr int kSupportedProtocolVersion = 1;

// NVS namespace/key names must stay <= 15 chars (NVS_KEY_NAME_MAX_SIZE-1).
constexpr const char* kReminderNs = "reminder_ctrl";
constexpr const char* kKeyUrl = "url";
constexpr const char* kKeyProtoVer = "proto_ver";
constexpr const char* kKeyConnTimeout = "conn_timeout";
constexpr const char* kKeyAssetTimeout = "asset_timeout";

bool StartsWith(const std::string& value, const char* prefix) {
    const size_t n = std::strlen(prefix);
    return value.size() >= n && value.compare(0, n, prefix) == 0;
}

bool ParseIpv4(const std::string& host, int out[4]) {
    int parts[4] = {};
    size_t pos = 0;
    for (int i = 0; i < 4; ++i) {
        if (pos >= host.size() || !std::isdigit(static_cast<unsigned char>(host[pos]))) {
            return false;
        }
        int value = 0;
        size_t digits = 0;
        while (pos < host.size() && std::isdigit(static_cast<unsigned char>(host[pos]))) {
            value = value * 10 + (host[pos] - '0');
            if (value > 255) return false;
            ++pos;
            ++digits;
        }
        if (digits == 0) return false;
        parts[i] = value;
        if (i < 3) {
            if (pos >= host.size() || host[pos] != '.') return false;
            ++pos;
        }
    }
    if (pos != host.size()) return false;
    for (int i = 0; i < 4; ++i) out[i] = parts[i];
    return true;
}
}  // namespace

ReminderControlClient& ReminderControlClient::GetInstance() {
    static ReminderControlClient instance;
    return instance;
}

bool ReminderControlClient::IsForbiddenHost(const std::string& host) {
    if (host.empty()) return true;
    std::string lower = host;
    for (char& c : lower) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    if (lower == "localhost" || lower == "127.0.0.1" || lower == "::1" ||
        lower == "0.0.0.0") {
        return true;
    }
    // Strip brackets for IPv6 literals; reject loopback / ULA / link-local lightly.
    if (!lower.empty() && lower.front() == '[') {
        if (lower.find("::1") != std::string::npos) return true;
        if (StartsWith(lower, "[fc") || StartsWith(lower, "[fd") ||
            StartsWith(lower, "[fe80")) {
            return true;
        }
    }
    int ip[4] = {};
    if (ParseIpv4(lower, ip)) {
        if (ip[0] == 10) return true;
        if (ip[0] == 127) return true;
        if (ip[0] == 0) return true;
        if (ip[0] == 169 && ip[1] == 254) return true;
        if (ip[0] == 192 && ip[1] == 168) return true;
        if (ip[0] == 172 && ip[1] >= 16 && ip[1] <= 31) return true;
        return false;
    }
    return false;
}

std::string ReminderControlClient::ExtractHost(const std::string& url) {
    size_t begin = 0;
    if (StartsWith(url, "wss://")) {
        begin = 6;
    } else if (StartsWith(url, "ws://")) {
        begin = 5;
    } else if (StartsWith(url, "https://")) {
        begin = 8;
    } else if (StartsWith(url, "http://")) {
        begin = 7;
    } else {
        return {};
    }
    size_t end = url.find_first_of("/?", begin);
    if (end == std::string::npos) end = url.size();
    if (end <= begin) return {};
    std::string host = url.substr(begin, end - begin);
    // Drop userinfo if present.
    const size_t at = host.find('@');
    if (at != std::string::npos) host = host.substr(at + 1);
    // Drop port.
    if (!host.empty() && host.front() != '[') {
        const size_t colon = host.find(':');
        if (colon != std::string::npos) host = host.substr(0, colon);
    }
    return host;
}

std::string ReminderControlClient::NormalizeHost(const std::string& host) {
    std::string out = host;
    for (char& c : out) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return out;
}

bool ReminderControlClient::ValidateConfig(
    const std::string& url, int protocol_version, int connect_timeout_ms,
    int asset_wait_timeout_ms, std::string* reason) {
    if (url.empty()) {
        if (reason) *reason = "missing_url";
        return false;
    }
    if (!StartsWith(url, "wss://")) {
        if (reason) *reason = StartsWith(url, "ws://") ? "not_wss" : "bad_scheme";
        return false;
    }
    if (url.size() > 512) {
        if (reason) *reason = "url_too_long";
        return false;
    }
    const std::string host = NormalizeHost(ExtractHost(url));
    if (host.empty()) {
        if (reason) *reason = "bad_host";
        return false;
    }
    if (IsForbiddenHost(host)) {
        if (reason) *reason = "forbidden_host";
        return false;
    }
    // Control URL must share the paired main WebSocket host. Never synthesize
    // the control URL from the main URL — only compare hosts.
    Settings main_settings("websocket", false);
    const std::string main_url = main_settings.GetString("url");
    if (main_url.empty()) {
        if (reason) *reason = "main_ws_missing";
        return false;
    }
    if (!StartsWith(main_url, "wss://")) {
        if (reason) *reason = "main_ws_not_wss";
        return false;
    }
    const std::string main_host = NormalizeHost(ExtractHost(main_url));
    if (main_host.empty()) {
        if (reason) *reason = "main_ws_bad_host";
        return false;
    }
    if (main_host != host) {
        if (reason) *reason = "host_mismatch";
        return false;
    }
    if (protocol_version != kSupportedProtocolVersion) {
        if (reason) *reason = "unsupported_version";
        return false;
    }
    if (connect_timeout_ms < 500 || connect_timeout_ms > 10000) {
        if (reason) *reason = "bad_connect_timeout";
        return false;
    }
    if (asset_wait_timeout_ms < 1000 || asset_wait_timeout_ms > 30000) {
        if (reason) *reason = "bad_asset_timeout";
        return false;
    }
    return true;
}

void ReminderControlClient::LoadPersistedConfig() {
    if (loaded_persisted_) return;
    loaded_persisted_ = true;
    Settings settings(kReminderNs, false);
    const std::string url = settings.GetString(kKeyUrl);
    const int version = settings.GetInt(kKeyProtoVer, 1);
    const int connect_ms = settings.GetInt(kKeyConnTimeout, 3000);
    const int asset_ms = settings.GetInt(kKeyAssetTimeout, 8000);
    if (url.empty()) return;
    std::string reason;
    if (!ValidateConfig(url, version, connect_ms, asset_ms, &reason)) {
        config_valid_ = false;
        url_.clear();
        ErasePersistedConfigLocked();
        ESP_LOGW(kTag,
                 "[REMINDER_CONTROL] event=config_updated status=cleared "
                 "reason=persisted_%s",
                 reason.c_str());
        return;
    }
    url_ = url;
    protocol_version_ = version;
    connect_timeout_ms_ = connect_ms;
    asset_wait_timeout_ms_ = asset_ms;
    config_valid_ = true;
}

void ReminderControlClient::ErasePersistedConfigLocked() {
    Settings settings(kReminderNs, true);
    if (!settings.IsValid()) {
        ESP_LOGW(kTag, "[REMINDER_CONTROL] event=nvs_unavailable op=erase");
        return;
    }
    settings.EraseKey(kKeyUrl);
    settings.EraseKey(kKeyProtoVer);
    settings.EraseKey(kKeyConnTimeout);
    settings.EraseKey(kKeyAssetTimeout);
}

void ReminderControlClient::PersistConfigLocked() {
    if (!config_valid_) {
        ErasePersistedConfigLocked();
        return;
    }
    Settings settings(kReminderNs, true);
    if (!settings.IsValid()) {
        ESP_LOGW(kTag, "[REMINDER_CONTROL] event=nvs_unavailable op=persist");
        return;
    }
    // Persist only non-sensitive control URL and timeouts. Never persist tokens.
    settings.SetString(kKeyUrl, url_);
    settings.SetInt(kKeyProtoVer, protocol_version_);
    settings.SetInt(kKeyConnTimeout, connect_timeout_ms_);
    settings.SetInt(kKeyAssetTimeout, asset_wait_timeout_ms_);
}

void ReminderControlClient::RequestCancel(CancelCode code) {
    cancel_code_.store(code);
    cancel_requested_.store(true);
}

ReminderControlClient::CancelCode ReminderControlClient::TakeCancelCode() {
    return cancel_code_.exchange(CancelCode::kNone);
}

ReminderControlClient::CancelCode ReminderControlClient::CancelCodeFromReason(
    const char* reason) {
    if (!reason || !*reason) return CancelCode::kCancelled;
    if (std::strcmp(reason, "preempted") == 0) return CancelCode::kPreempted;
    if (std::strcmp(reason, "disconnected") == 0) {
        return CancelCode::kDisconnected;
    }
    if (std::strcmp(reason, "voice_error") == 0) return CancelCode::kVoiceError;
    if (std::strcmp(reason, "main_ws_available") == 0) {
        return CancelCode::kMainWsAvailable;
    }
    if (std::strcmp(reason, "device_busy") == 0) return CancelCode::kDeviceBusy;
    if (std::strcmp(reason, "absence") == 0) return CancelCode::kAbsence;
    if (std::strcmp(reason, "user_action") == 0) return CancelCode::kUserAction;
    if (std::strcmp(reason, "config_cleared") == 0 ||
        std::strcmp(reason, "capability_missing") == 0) {
        return CancelCode::kConfigCleared;
    }
    if (std::strcmp(reason, "gate") == 0) return CancelCode::kGate;
    return CancelCode::kCancelled;
}

const char* ReminderControlClient::CancelCodeName(CancelCode code) {
    switch (code) {
        case CancelCode::kNone: return "cancelled";
        case CancelCode::kCancelled: return "cancelled";
        case CancelCode::kPreempted: return "preempted";
        case CancelCode::kDisconnected: return "disconnected";
        case CancelCode::kVoiceError: return "voice_error";
        case CancelCode::kMainWsAvailable: return "main_ws_available";
        case CancelCode::kDeviceBusy: return "device_busy";
        case CancelCode::kAbsence: return "absence";
        case CancelCode::kUserAction: return "user_action";
        case CancelCode::kConfigCleared: return "config_cleared";
        case CancelCode::kGate: return "gate";
    }
    return "cancelled";
}

void ReminderControlClient::ClearConfig(const char* reason) {
    RequestCancel(CancelCode::kConfigCleared);
    std::lock_guard<std::mutex> lock(mutex_);
    loaded_persisted_ = true;
    config_valid_ = false;
    url_.clear();
    protocol_version_ = 1;
    connect_timeout_ms_ = 3000;
    asset_wait_timeout_ms_ = 8000;
    has_pending_ = false;
    pending_ = Request{};
    ErasePersistedConfigLocked();
    ESP_LOGI(kTag,
             "[REMINDER_CONTROL] event=config_updated status=cleared "
             "reason=%s",
             reason ? reason : "capability_missing");
}

void ReminderControlClient::SetConfig(const std::string& url,
                                      int protocol_version,
                                      int connect_timeout_ms,
                                      int asset_wait_timeout_ms) {
    std::string reason;
    if (!ValidateConfig(url, protocol_version, connect_timeout_ms,
                        asset_wait_timeout_ms, &reason)) {
        // Invalid capability must clear any stale persisted control URL.
        RequestCancel(CancelCode::kConfigCleared);
        {
            std::lock_guard<std::mutex> lock(mutex_);
            loaded_persisted_ = true;
            config_valid_ = false;
            url_.clear();
            has_pending_ = false;
            pending_ = Request{};
            ErasePersistedConfigLocked();
        }
        ESP_LOGW(kTag,
                 "[REMINDER_CONTROL] event=config_updated status=rejected "
                 "reason=%s",
                 reason.c_str());
        return;
    }
    std::lock_guard<std::mutex> lock(mutex_);
    loaded_persisted_ = true;
    url_ = url;
    protocol_version_ = protocol_version;
    connect_timeout_ms_ = connect_timeout_ms;
    asset_wait_timeout_ms_ = asset_wait_timeout_ms;
    config_valid_ = true;
    PersistConfigLocked();
    ESP_LOGI(kTag,
             "[REMINDER_CONTROL] event=config_updated status=accepted "
             "version=%d connect_ms=%d asset_ms=%d host=%s",
             protocol_version_, connect_timeout_ms_, asset_wait_timeout_ms_,
             NormalizeHost(ExtractHost(url_)).c_str());
}

bool ReminderControlClient::HasValidConfig() const {
    std::lock_guard<std::mutex> lock(mutex_);
    const_cast<ReminderControlClient*>(this)->LoadPersistedConfig();
    return config_valid_ && !url_.empty();
}

std::string ReminderControlClient::UrlHostForLog() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return ExtractHost(url_);
}

bool ReminderControlClient::IsBusy() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return worker_ != nullptr || state_ == State::kConnecting ||
           state_ == State::kSendingRequest ||
           state_ == State::kWaitingAsset || has_pending_;
}

bool ReminderControlClient::ParseRequest(const std::string& payload_json,
                                         Request* out) {
    if (!out) return false;
    cJSON* root = cJSON_Parse(payload_json.c_str());
    if (!root) return false;
    auto* type = cJSON_GetObjectItem(root, "type");
    auto* instance = cJSON_GetObjectItem(root, "instance_id");
    auto* revision = cJSON_GetObjectItem(root, "revision");
    auto* voice_revision = cJSON_GetObjectItem(root, "voice_revision");
    auto* presence_generation =
        cJSON_GetObjectItem(root, "presence_generation");
    auto* recipient = cJSON_GetObjectItem(root, "recipient_person_id");
    const bool ok =
        cJSON_IsString(type) && type->valuestring &&
        std::strcmp(type->valuestring, "reminder_voice_request") == 0 &&
        cJSON_IsString(instance) && instance->valuestring &&
        cJSON_IsNumber(revision) && cJSON_IsNumber(voice_revision) &&
        cJSON_IsNumber(presence_generation) &&
        cJSON_IsString(recipient) && recipient->valuestring &&
        revision->valuedouble >= 1 &&
        voice_revision->valuedouble >= 1 &&
        presence_generation->valuedouble >= 0 &&
        std::floor(revision->valuedouble) == revision->valuedouble &&
        std::floor(voice_revision->valuedouble) ==
            voice_revision->valuedouble &&
        std::floor(presence_generation->valuedouble) ==
            presence_generation->valuedouble;
    if (ok) {
        out->payload_json = payload_json;
        out->instance_id = instance->valuestring;
        out->revision = static_cast<uint32_t>(revision->valuedouble);
        out->voice_revision =
            static_cast<uint32_t>(voice_revision->valuedouble);
        out->presence_generation =
            static_cast<uint32_t>(presence_generation->valuedouble);
        out->recipient_person_id = recipient->valuestring;
        out->priority_rank = PriorityRankForInstance(out->instance_id);
    }
    cJSON_Delete(root);
    return ok;
}

int ReminderControlClient::PriorityRankForInstance(
    const std::string& instance_id) {
    ReminderInstance instance;
    if (!ReminderCoordinator::GetInstance().GetById(instance_id, instance)) {
        return 50;
    }
    if (instance.priority == ReminderPriority::kHigh) return 0;
    if (instance.priority == ReminderPriority::kNormal) return 2;
    return 3;
}

bool ReminderControlClient::PassesDeliveryGate(const Request& request,
                                               const char** reason) const {
    if (Application::GetInstance().GetDeviceState() != kDeviceStateIdle) {
        if (reason) *reason = "device_busy";
        return false;
    }
    if (Application::GetInstance().IsMainAudioChannelOpened()) {
        if (reason) *reason = "main_ws_available";
        return false;
    }
    ReminderInstance current;
    if (!ReminderCoordinator::GetInstance().GetCurrent(current)) {
        if (reason) *reason = "no_current_card";
        return false;
    }
    if (current.instance_id != request.instance_id) {
        if (reason) *reason = "card_replaced";
        return false;
    }
    if (current.status != ReminderStatus::kPresenting) {
        if (reason) *reason = "not_presenting";
        return false;
    }
    if (current.revision != request.revision) {
        if (reason) *reason = "revision_mismatch";
        return false;
    }
    if (current.voice_revision != request.voice_revision) {
        if (reason) *reason = "voice_revision_mismatch";
        return false;
    }
    if (current.delivery_presence_generation != request.presence_generation) {
        if (reason) *reason = "presence_generation_mismatch";
        return false;
    }
    auto& presence = PresenceContext::GetInstance();
    if (!presence.IsRadarPresent()) {
        if (reason) *reason = "absence";
        return false;
    }
    if (presence.PresenceGeneration() != request.presence_generation) {
        if (reason) *reason = "stale_generation";
        return false;
    }
    const bool speaker_matches =
        UserContext::GetInstance().GetCurrentSpeakerUserId() ==
        request.recipient_person_id;
    if (request.recipient_person_id != "all" && !speaker_matches &&
        !presence.ConfirmedMatches(request.recipient_person_id,
                                   request.presence_generation)) {
        if (reason) *reason = "identity_mismatch";
        return false;
    }
    if (reason) *reason = nullptr;
    return true;
}

void ReminderControlClient::EnqueueFromVoiceRequest(
    const std::string& payload_json) {
    Request request;
    if (!ParseRequest(payload_json, &request)) {
        ESP_LOGW(kTag,
                 "[REMINDER_CONTROL] event=request_queued status=rejected "
                 "reason=bad_payload");
        return;
    }
    {
        std::lock_guard<std::mutex> lock(mutex_);
        LoadPersistedConfig();
        if (!config_valid_) {
            ESP_LOGW(kTag,
                     "[REMINDER_CONTROL] event=request_queued status=rejected "
                     "reason=no_capability instance=%s",
                     request.instance_id.c_str());
            return;
        }
    }
    const char* gate_reason = nullptr;
    if (!PassesDeliveryGate(request, &gate_reason)) {
        ESP_LOGW(kTag,
                 "[REMINDER_CONTROL] event=request_queued status=rejected "
                 "reason=%s instance=%s",
                 gate_reason ? gate_reason : "gate",
                 request.instance_id.c_str());
        return;
    }

    std::lock_guard<std::mutex> lock(mutex_);
    const bool same_as_active =
        worker_ != nullptr &&
        active_.instance_id == request.instance_id &&
        active_.revision == request.revision &&
        active_.voice_revision == request.voice_revision &&
        active_.presence_generation == request.presence_generation;
    if (same_as_active) {
        ESP_LOGI(kTag,
                 "[REMINDER_CONTROL] event=request_queued status=dedup "
                 "instance=%s",
                 request.instance_id.c_str());
        return;
    }
    if (has_pending_ &&
        pending_.instance_id == request.instance_id &&
        pending_.revision == request.revision &&
        pending_.voice_revision == request.voice_revision &&
        pending_.presence_generation == request.presence_generation) {
        ESP_LOGI(kTag,
                 "[REMINDER_CONTROL] event=request_queued status=dedup "
                 "instance=%s",
                 request.instance_id.c_str());
        return;
    }

    if (worker_ == nullptr) {
        active_ = std::move(request);
        ESP_LOGI(kTag,
                 "[REMINDER_CONTROL] event=request_queued status=accepted "
                 "instance=%s rev=%u voice_rev=%u gen=%u",
                 active_.instance_id.c_str(),
                 static_cast<unsigned>(active_.revision),
                 static_cast<unsigned>(active_.voice_revision),
                 static_cast<unsigned>(active_.presence_generation));
        StartWorkerLocked();
        return;
    }

    // Busy: keep only the highest-priority pending request.
    if (!has_pending_ || request.priority_rank < pending_.priority_rank) {
        pending_ = std::move(request);
        has_pending_ = true;
        ESP_LOGI(kTag,
                 "[REMINDER_CONTROL] event=request_queued status=pending "
                 "instance=%s rank=%d",
                 pending_.instance_id.c_str(), pending_.priority_rank);
    } else {
        ESP_LOGI(kTag,
                 "[REMINDER_CONTROL] event=request_queued status=dropped "
                 "reason=lower_priority instance=%s",
                 request.instance_id.c_str());
        return;
    }

    if (has_pending_ && pending_.priority_rank < active_.priority_rank) {
        RequestCancel(CancelCode::kPreempted);
        ESP_LOGI(kTag,
                 "[REMINDER_CONTROL] event=cancelled reason=preempted "
                 "old=%s new=%s",
                 active_.instance_id.c_str(), pending_.instance_id.c_str());
    }
}

void ReminderControlClient::Cancel(const char* reason) {
    const CancelCode code = CancelCodeFromReason(reason);
    RequestCancel(code);
    std::lock_guard<std::mutex> lock(mutex_);
    has_pending_ = false;
    pending_ = Request{};
    if (worker_ == nullptr) {
        state_ = State::kIdle;
        return;
    }
    ESP_LOGI(kTag, "[REMINDER_CONTROL] event=cancelled reason=%s",
             CancelCodeName(code));
}

void ReminderControlClient::OnMainChannelBecameAvailable() {
    Cancel("main_ws_available");
}

void ReminderControlClient::OnDeviceStateChanged(DeviceState state) {
    if (state == kDeviceStateListening || state == kDeviceStateSpeaking ||
        state == kDeviceStateConnecting) {
        Cancel("device_busy");
    }
}

void ReminderControlClient::StartWorkerLocked() {
    cancel_requested_.store(false);
    asset_done_.store(false);
    cancel_code_.store(CancelCode::kNone);
    state_ = State::kConnecting;
    const BaseType_t created = xTaskCreate(
        WorkerEntry, "rem_ctrl", 6144, this, 2, &worker_);
    if (created != pdPASS) {
        worker_ = nullptr;
        state_ = State::kFailed;
        ESP_LOGW(kTag,
                 "[REMINDER_CONTROL] event=connect_failed reason=task_create");
    }
}

void ReminderControlClient::WorkerEntry(void* arg) {
    static_cast<ReminderControlClient*>(arg)->WorkerLoop();
    vTaskDelete(nullptr);
}

void ReminderControlClient::CloseSocket() {
    socket_.reset();
}

void ReminderControlClient::Finish(State terminal, const char* event,
                                   const char* reason) {
    CloseSocket();
    Request next;
    bool start_next = false;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        state_ = terminal;
        ESP_LOGI(kTag,
                 "[REMINDER_CONTROL] event=%s reason=%s instance=%s",
                 event ? event : "closed",
                 reason ? reason : "-",
                 active_.instance_id.empty() ? "-"
                                             : active_.instance_id.c_str());
        ESP_LOGI(kTag, "[REMINDER_CONTROL] event=closed");
        worker_ = nullptr;
        state_ = State::kIdle;
        active_ = Request{};
        if (has_pending_) {
            next = std::move(pending_);
            pending_ = Request{};
            has_pending_ = false;
            active_ = next;
            start_next = true;
            StartWorkerLocked();
        }
    }
    (void)start_next;
}

void ReminderControlClient::HandleErrorMessage(const cJSON* root) {
    auto* code = cJSON_GetObjectItem(root, "code");
    const char* code_str =
        (cJSON_IsString(code) && code->valuestring) ? code->valuestring
                                                    : "error";
    ESP_LOGW(kTag,
             "[REMINDER_CONTROL] event=asset_discard reason=voice_error "
             "code=%s",
             code_str);
    asset_done_.store(true);
    RequestCancel(CancelCode::kVoiceError);
}

void ReminderControlClient::HandleAssetMessage(const cJSON* root) {
    Request snapshot;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        snapshot = active_;
    }
    const char* gate_reason = nullptr;
    if (!PassesDeliveryGate(snapshot, &gate_reason)) {
        ESP_LOGW(kTag,
                 "[REMINDER_CONTROL] event=asset_discard reason=%s",
                 gate_reason ? gate_reason : "gate");
        asset_done_.store(true);
        cancel_requested_.store(true);
        return;
    }

    auto* instance = cJSON_GetObjectItem(root, "instance_id");
    auto* voice_revision = cJSON_GetObjectItem(root, "voice_revision");
    auto* phase = cJSON_GetObjectItem(root, "phase");
    auto* script = cJSON_GetObjectItem(root, "script");
    auto* url = cJSON_GetObjectItem(root, "url");
    auto* sha256 = cJSON_GetObjectItem(root, "sha256");
    auto* format = cJSON_GetObjectItem(root, "format");
    auto* bytes = cJSON_GetObjectItem(root, "bytes");
    if (!(cJSON_IsString(instance) && instance->valuestring &&
          cJSON_IsNumber(voice_revision) && cJSON_IsString(phase) &&
          cJSON_IsString(script) && script->valuestring &&
          std::strlen(script->valuestring) <= 256 && cJSON_IsString(url) &&
          cJSON_IsString(sha256) && cJSON_IsString(format) &&
          cJSON_IsNumber(bytes) && voice_revision->valuedouble >= 1 &&
          bytes->valuedouble >= 1 &&
          std::floor(voice_revision->valuedouble) ==
              voice_revision->valuedouble &&
          std::floor(bytes->valuedouble) == bytes->valuedouble)) {
        ESP_LOGW(kTag,
                 "[REMINDER_CONTROL] event=asset_discard reason=bad_asset");
        asset_done_.store(true);
        cancel_requested_.store(true);
        return;
    }
    if (snapshot.instance_id != instance->valuestring ||
        snapshot.voice_revision !=
            static_cast<uint32_t>(voice_revision->valuedouble)) {
        ESP_LOGW(kTag,
                 "[REMINDER_CONTROL] event=asset_discard "
                 "reason=instance_mismatch");
        asset_done_.store(true);
        cancel_requested_.store(true);
        return;
    }

    ESP_LOGI(kTag,
             "[REMINDER_CONTROL] event=asset_received instance=%s "
             "voice_rev=%u",
             snapshot.instance_id.c_str(),
             static_cast<unsigned>(snapshot.voice_revision));

    ReminderVoiceAsset asset;
    asset.phase = phase->valuestring;
    asset.script = script->valuestring;
    asset.url = url->valuestring;
    asset.sha256 = sha256->valuestring;
    asset.format = format->valuestring;
    asset.byte_count = static_cast<uint32_t>(bytes->valuedouble);
    const std::string instance_id = snapshot.instance_id;
    const uint32_t voice_rev = snapshot.voice_revision;
    const uint32_t revision = snapshot.revision;
    const uint32_t presence_generation = snapshot.presence_generation;
    const std::string recipient = snapshot.recipient_person_id;

    const bool started = ReminderVoiceService::GetInstance().CacheAssetAsync(
        instance_id, voice_rev, asset,
        [this, instance_id, voice_rev, revision, presence_generation,
         recipient](bool ok, const ReminderVoiceAsset& cached,
                    const std::string& error) {
            (void)error;
            Request gate_request;
            gate_request.instance_id = instance_id;
            gate_request.revision = revision;
            gate_request.voice_revision = voice_rev;
            gate_request.presence_generation = presence_generation;
            gate_request.recipient_person_id = recipient;
            const char* reason = nullptr;
            if (!ok) {
                ESP_LOGW(kTag,
                         "[REMINDER_CONTROL] event=asset_discard "
                         "reason=cache_failed");
                asset_done_.store(true);
                RequestCancel(CancelCode::kVoiceError);
                return;
            }
            if (!PassesDeliveryGate(gate_request, &reason)) {
                std::remove(cached.cache_path.c_str());
                ESP_LOGW(kTag,
                         "[REMINDER_CONTROL] event=asset_discard reason=%s",
                         reason ? reason : "stale");
                asset_done_.store(true);
                RequestCancel(CancelCode::kGate);
                return;
            }
            // Shared accept+play entry with main WebSocket path.
            if (ReminderVoiceService::GetInstance()
                    .AcceptCachedAssetAndMaybePlay(
                        instance_id, revision, voice_rev,
                        presence_generation, recipient, cached)) {
                ESP_LOGI(kTag,
                         "[REMINDER_CONTROL] event=asset_accepted "
                         "instance=%s voice_rev=%u",
                         instance_id.c_str(),
                         static_cast<unsigned>(voice_rev));
            } else {
                ESP_LOGW(kTag,
                         "[REMINDER_CONTROL] event=asset_discard "
                         "reason=update_or_play_rejected");
            }
            asset_done_.store(true);
        });
    if (!started) {
        ESP_LOGW(kTag,
                 "[REMINDER_CONTROL] event=asset_discard "
                 "reason=cache_not_started");
        asset_done_.store(true);
        cancel_requested_.store(true);
    }
}

void ReminderControlClient::HandleIncomingText(const std::string& text) {
    cJSON* root = cJSON_Parse(text.c_str());
    if (!root) return;
    auto* type = cJSON_GetObjectItem(root, "type");
    if (cJSON_IsString(type) && type->valuestring) {
        if (std::strcmp(type->valuestring, "reminder_voice_asset") == 0) {
            HandleAssetMessage(root);
        } else if (std::strcmp(type->valuestring, "reminder_voice_error") ==
                   0) {
            HandleErrorMessage(root);
        }
    }
    cJSON_Delete(root);
}

void ReminderControlClient::WorkerLoop() {
    Request request;
    std::string url;
    int connect_timeout_ms = 3000;
    int asset_wait_timeout_ms = 8000;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        request = active_;
        url = url_;
        connect_timeout_ms = connect_timeout_ms_;
        asset_wait_timeout_ms = asset_wait_timeout_ms_;
        state_ = State::kConnecting;
    }

    const char* gate_reason = nullptr;
    if (cancel_requested_.load() ||
        !PassesDeliveryGate(request, &gate_reason)) {
        const CancelCode code = cancel_code_.load();
        Finish(State::kCancelled, "cancelled",
               cancel_requested_.load()
                   ? CancelCodeName(code)
                   : (gate_reason ? gate_reason : "gate"));
        return;
    }

    ESP_LOGI(kTag,
             "[REMINDER_CONTROL] event=connect_start instance=%s host=%s "
             "timeout_ms=%d",
             request.instance_id.c_str(), ExtractHost(url).c_str(),
             connect_timeout_ms);

    auto network = Board::GetInstance().GetNetwork();
    if (!network) {
        Finish(State::kFailed, "connect_failed", "no_network");
        return;
    }
    socket_ = network->CreateWebSocket(2);
    if (!socket_) {
        Finish(State::kFailed, "connect_failed", "socket_create");
        return;
    }

    Settings settings("websocket", false);
    std::string token = settings.GetString("token");
    const int version = settings.GetInt("version", 1);
    if (!token.empty()) {
        if (token.find(' ') == std::string::npos) {
            token = "Bearer " + token;
        }
        socket_->SetHeader("Authorization", token.c_str());
    }
    const std::string proto_ver = std::to_string(version > 0 ? version : 1);
    socket_->SetHeader("Protocol-Version", proto_ver.c_str());
    socket_->SetHeader("Device-Id", SystemInfo::GetMacAddress().c_str());
    socket_->SetHeader("Client-Id", Board::GetInstance().GetUuid().c_str());
    socket_->SetHeader("X-Reminder-Control", "1");

    socket_->OnData([this](const char* data, size_t len, bool binary) {
        if (binary || !data || len == 0) return;
        HandleIncomingText(std::string(data, len));
    });
    socket_->OnDisconnected([this]() {
        if (!asset_done_.load()) {
            RequestCancel(CancelCode::kDisconnected);
        }
    });

    if (cancel_requested_.load() ||
        !socket_->Connect(url.c_str(), connect_timeout_ms)) {
        const char* fail_reason =
            cancel_requested_.load()
                ? CancelCodeName(cancel_code_.load())
                : "timeout";
        ESP_LOGW(kTag,
                 "[REMINDER_CONTROL] event=connect_failed reason=%s",
                 fail_reason);
        Finish(State::kFailed, "connect_failed", fail_reason);
        return;
    }
    {
        std::lock_guard<std::mutex> lock(mutex_);
        state_ = State::kSendingRequest;
    }
    ESP_LOGI(kTag, "[REMINDER_CONTROL] event=connect_ok instance=%s",
             request.instance_id.c_str());

    if (cancel_requested_.load() ||
        !PassesDeliveryGate(request, &gate_reason)) {
        Finish(State::kCancelled, "cancelled",
               cancel_requested_.load()
                   ? CancelCodeName(cancel_code_.load())
                   : (gate_reason ? gate_reason : "gate"));
        return;
    }
    if (Application::GetInstance().IsMainAudioChannelOpened()) {
        RequestCancel(CancelCode::kMainWsAvailable);
        Finish(State::kCancelled, "cancelled", "main_ws_available");
        return;
    }

    if (!socket_->Send(request.payload_json)) {
        Finish(State::kFailed, "connect_failed", "send_failed");
        return;
    }
    {
        std::lock_guard<std::mutex> lock(mutex_);
        state_ = State::kWaitingAsset;
    }
    ESP_LOGI(kTag,
             "[REMINDER_CONTROL] event=request_sent instance=%s rev=%u "
             "voice_rev=%u",
             request.instance_id.c_str(),
             static_cast<unsigned>(request.revision),
             static_cast<unsigned>(request.voice_revision));

    const int wait_slices = (asset_wait_timeout_ms + 99) / 100;
    for (int i = 0; i < wait_slices; ++i) {
        if (asset_done_.load()) {
            Finish(State::kCompleted, "asset_accepted", "ok");
            return;
        }
        if (cancel_requested_.load()) {
            Finish(State::kCancelled, "cancelled",
                   CancelCodeName(cancel_code_.load()));
            return;
        }
        if (!PassesDeliveryGate(request, &gate_reason)) {
            Finish(State::kCancelled, "cancelled",
                   gate_reason ? gate_reason : "gate");
            return;
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
    ESP_LOGW(kTag,
             "[REMINDER_CONTROL] event=timeout reason=asset_wait "
             "instance=%s",
             request.instance_id.c_str());
    Finish(State::kFailed, "timeout", "asset_wait");
}
